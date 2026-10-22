// Agent Frida cho bảng điều khiển (control_panel.py): đọc trạng thái nhân vật, bật/tắt cờ MOD, ẩn game (ép ngủ).
// Việc gọi vào Unity (đổi FPS) chạy trong Main.FixedUpdate (luồng chính); đọc trạng thái 1 lần/giây rồi trả bản đã lưu.

const mod = Process.getModuleByName('GameAssembly.dll');
const base = mod.base;

const RVA = {
  mainFixedUpdate: 0x5086e0,
  setTargetFrameRate: 0x94eaa0, // Application.set_targetFrameRate
  sleepCave: 0x330ce0,          // cave chế độ ngủ (patch_vqmm.py) - bắt đầu bằng cmp byte [FORCE], 0
  pickCounter: 0x331100,        // bộ đếm nhặt đồ (lock inc ...)
  dataForce: 0xefbd80,          // byte ép ngủ
  dataPicked: 0xefbd20,         // số lần nhặt (u64)
};
const OFF = {
  bhMyChar: 0xa8, chName: 0x190, chHp: 0xd0, chHpFull: 0x108, chMp: 0xc8, chMpFull: 0x110, chStatus: 0x88,
  jbMapName: 0x70, jbZoneId: 0x84,
  ftFps: 0x1a,
};
// cờ MOD: [class, offset]
const FLAGS = {
  ts: ['rs', 0x10],   // Tàn sát
  nhat: ['rs', 0x40], // Tự động nhặt
  ak: ['fg', 0x0],    // Tự đánh
  ahs: ['fg', 0x20],  // Tự động hồi sinh (fs.cpy gọi fg.cng khi cờ bật)
};

function api(name, ret, args) { return new NativeFunction(mod.getExportByName(name), ret, args); }
const il2cpp_domain_get = api('il2cpp_domain_get', 'pointer', []);
const il2cpp_domain_get_assemblies = api('il2cpp_domain_get_assemblies', 'pointer', ['pointer', 'pointer']);
const il2cpp_assembly_get_image = api('il2cpp_assembly_get_image', 'pointer', ['pointer']);
const il2cpp_image_get_name = api('il2cpp_image_get_name', 'pointer', ['pointer']);
const il2cpp_class_from_name = api('il2cpp_class_from_name', 'pointer', ['pointer', 'pointer', 'pointer']);
const setFps = new NativeFunction(base.add(RVA.setTargetFrameRate), 'void', ['int', 'pointer']);

function findImage() {
  const n = Memory.alloc(8);
  const asms = il2cpp_domain_get_assemblies(il2cpp_domain_get(), n);
  for (let i = 0; i < n.readU64().toNumber(); i++) {
    const img = il2cpp_assembly_get_image(asms.add(i * 8).readPointer());
    if (il2cpp_image_get_name(img).readUtf8String() === 'Assembly-CSharp.dll') return img;
  }
  throw new Error('Không tìm thấy Assembly-CSharp.dll');
}
const image = findImage();
const K = {};
for (const full of ['bh', 'fg', 'ft', 'jb', 'Mod.XMAP.rs']) {
  const dot = full.lastIndexOf('.');
  const k = il2cpp_class_from_name(image, Memory.allocUtf8String(dot < 0 ? '' : full.slice(0, dot)), Memory.allocUtf8String(full.slice(dot + 1)));
  if (k.isNull()) throw new Error('Thiếu class ' + full + ' - client khác phiên bản?');
  K[full.slice(dot + 1)] = k;
}

function statics(k) { return k.add(0xb8).readPointer(); } // null khi class chưa khởi tạo
function str(p) { return p.isNull() ? '' : p.add(0x14).readUtf16String(p.add(0x10).readS32()); }
const hasForce = () => base.add(RVA.sleepCave).readU16() === 0x3d80;   // DLL đã vá bản có cờ ép ngủ
const hasPickCounter = () => base.add(RVA.pickCounter).readU8() === 0xf0;

let snap = { ready: false };
let savedFps = null;     // FPS trước khi ẩn
const pending = [];      // việc cần chạy trên luồng chính

function readSnap() {
  const s = { ready: false, hidden: hasForce() && base.add(RVA.dataForce).readU8() !== 0, canHide: hasForce(),
              picked: hasPickCounter() ? base.add(RVA.dataPicked).readU64().toNumber() : null, flags: {} };
  const ft = statics(K.ft);
  s.fps = ft.isNull() ? 0 : ft.add(OFF.ftFps).readS16();
  for (const [name, [cls, off]] of Object.entries(FLAGS)) {
    const st = statics(K[cls]);
    s.flags[name] = st.isNull() ? null : st.add(off).readU8() !== 0;
  }
  const bh = statics(K.bh), jb = statics(K.jb);
  const me = bh.isNull() ? NULL : bh.add(OFF.bhMyChar).readPointer();
  if (me.isNull() || jb.isNull()) return s;
  if (!str(me.add(OFF.chName).readPointer())) return s; // đang ở màn hình đăng nhập / tải
  Object.assign(s, {
    ready: true,
    name: str(me.add(OFF.chName).readPointer()),
    hp: me.add(OFF.chHp).readS64().toNumber(), hpFull: me.add(OFF.chHpFull).readS64().toNumber(),
    mp: me.add(OFF.chMp).readS64().toNumber(), mpFull: me.add(OFF.chMpFull).readS64().toNumber(),
    dead: me.add(OFF.chStatus).readS32() === 14,
    map: str(jb.add(OFF.jbMapName).readPointer()), zone: jb.add(OFF.jbZoneId).readS32(),
  });
  return s;
}

function applyFps(fps) {
  const ft = statics(K.ft);
  if (!ft.isNull()) ft.add(OFF.ftFps).writeS16(fps);
  setFps(fps, NULL);
}

let lastSnap = 0, busy = false;
Interceptor.attach(base.add(RVA.mainFixedUpdate), {
  onEnter() {
    if (busy) return;
    busy = true;
    try {
      while (pending.length) pending.shift()();
      const now = Date.now();
      if (now - lastSnap >= 1000) { lastSnap = now; snap = readSnap(); }
    } catch (e) {
      snap = { ready: false, error: String(e) };
    }
    busy = false;
  },
});

rpc.exports = {
  status() { return snap; },
  setFlag(name, on) {
    const f = FLAGS[name];
    if (!f) return false;
    pending.push(() => { const st = statics(K[f[0]]); if (!st.isNull()) st.add(f[1]).writeU8(on ? 1 : 0); });
    return true;
  },
  // Ẩn: ép ngủ (không vẽ gì) + hạ FPS; hiện: thôi ép ngủ + trả FPS cũ
  setHidden(on, hiddenFps) {
    if (!hasForce()) return false;
    pending.push(() => {
      const force = base.add(RVA.dataForce);
      if (on) {
        if (force.readU8() === 0) { const ft = statics(K.ft); savedFps = ft.isNull() ? 60 : ft.add(OFF.ftFps).readS16(); }
        force.writeU8(1);
        applyFps(hiddenFps);
      } else if (force.readU8() !== 0) {
        force.writeU8(0);
        applyFps(savedFps && savedFps > 5 ? savedFps : 60);
      }
    });
    return true;
  },
};
