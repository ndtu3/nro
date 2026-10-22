// Agent Frida chạy bên trong NgocRongViet.exe: săn cụm BOSS tự động.
// Mọi lời gọi vào game đều chạy trong Main.FixedUpdate (luồng chính của Unity).
// Địa chỉ/offset dưới đây dịch ngược từ bản client NgocRongViet hiện tại (Unity 2022.3.37f1,
// metadata v31); client cập nhật thì phải dò lại.

const mod = Process.getModuleByName('GameAssembly.dll');
const base = mod.base;

const RVA = {
  mainFixedUpdate: 0x5086e0, // Main.FixedUpdate()
  xmapStart: 0x46e5f0,       // Mod.XMAP.sa.hrr(int mapId)   - XMAP tới map (bản Mod2.XMAP không chạy)
  changeZone: 0x230c70,      // hx.dqn(int zoneId, int indexUI) - Service.requestChangeZone
  charMove: 0x230df0,        // hx.dqp()                      - Service.charMove
  openZoneUI: 0x232000,      // hx.drd()                      - Service.openUIZone (lệnh 29)
  reviveHere: 0x2335f0,      // hx.drv()                      - Service.wakeUpFromDead (lệnh -16, hồi sinh tại chỗ)
  returnHome: 0x233490,      // hx.dru()                      - Service.returnTownFromDead (lệnh -15, về nhà)
  useSkillNotFocus: 0x4d5620, // dg.bvq(Skill)                - GameScr.doUseSkillNotFocus (skill tự dùng: Biến khỉ, TDHS...)
  selectSkillSrv: 0x231c50,  // hx.drb(int templateId)        - Service.selectSkill (lệnh 0x22)
  modInstance: 0x549ba0,     // fz.cqq()                      - instance xử lý menu MOD (Mod2)
  panelHide: 0x1edfa0,       // gz.dfl()                      - Panel.hide()
  modAction: 0x543450,       // fz.bgi(int id, object p)      - thực thi mục menu MOD / lệnh chat
  teleport: 0x537f10,        // fp.cpj(int x, int y)          - MOD: đặt cx/cy + charMove
  focusTo: 0x19aa70,         // bh.bee(Object)                - Char.focusManualTo (NPC/quái/nhân vật)
  openNpcMenu: 0x232340,     // hx.drf(int npcTemplateId)     - Service.openMenu (lệnh 33)
  menuClose: 0x50d360,       // Menu.chz()                    - đóng menu (+0x84 = 1: thực hiện mục đang chọn)
  chatPopupPerform: 0x1b5700, // bj.bgi(int id, object p)     - ChatPopup: 8000 = dòng tiếp, 1001 = đóng
};

const OFF = {
  // static fields
  fqBossList: 0x8,     // fq.mnl : MyVector<j> danh sách BOSS thông báo
  fqNotifyBoss: 0x5,   // fq.mnk : Thông báo BOSS [Bật]
  fgAutoAttack: 0x0,   // fg.mjn : Tự đánh (ak)
  fgFocusBoss: 0x10,   // fg.mjp : Focus BOSS của MOD (tự đổi charFocus)
  fgLocateBoss: 0xc8,  // fg.mla : Định vị BOSS của MOD - chỉ là nhãn menu
  fgLocateTarget: 0xc0, // fg: tên boss đã chọn "Định vị" - thông báo boss trùng tên là MOD tự XMAP tới ngay
  fgKeepFocus: 0xc9,   // fg: chặn game tự đổi mục tiêu khi đang có charFocus
  rsKillMobs: 0x10, rsKillChars: 0x11, rsGoback: 0x15, // Mod.XMAP.rs: Tàn sát / Tàn sát người / Goback Tọa Độ
  dgAutoPlay: 0x364,   // GameScr static: auto-play của game (bị đánh thì tự đổi khu ngẫu nhiên)
  stringEmptySlot: 0xc07728, // TypeInfo System.String -> statics +0 = String.Empty
  // ---- nhiệm vụ (Task = class iv ở Char+0x238; server gửi NPC/map cho từng bước) ----
  chTask: 0x238, tkStep: 0x10, tkCounts: 0x18, tkId: 0x20, tkTitles: 0x38, tkProgress: 0x48,
  dgTaskNpc: 0x1b0, dgTaskMap: 0x1b8, // GameScr static Int32[]: NPC template / map của từng bước
  chHintX: 0x3a8, chHintY: 0x3aa,     // điểm nhấp nháy (TASK_UPDATE)
  dgMobs: 0x110, dgNpcs: 0x118,       // GameScr.vMob / vNpc
  npcTemplate: 0x760, npcHide: 0x774, tplNpcId: 0x10, tplNpcName: 0x18,
  mobTemplateId: 0xe0, mobStatus: 0x70, mobHp: 0x50, mobIsMine: 0x103, mobTplName: 0x18, // Mob(fa); fa static +0 = MobTemplate[]
  menuItems: 0x18, menuSelected: 0x20, menuPerformOnClose: 0x84, menuCancel: 0x85, cmdCaption: 0x20, cmdSubCaption: 0x28,
  bjCurr: 0x10, bjServer: 0x18, bjPerformDelay: 0x3c, bhLockKey: 0xe2, // ChatPopup statics / Char.isLockKey
  rvXmapRunning: 0x0,  // Mod.XMAP.rv : XMAP đang chạy
  jbMapId: 0x7c,       // TileMap.mapID
  jbMapName: 0x70,     // TileMap.mapName
  jbZoneId: 0x84,      // TileMap.zoneID
  dgCharInMap: 0xf0,   // GameScr.vCharInMap
  dgInstance: 0x18,    // GameScr.gI()
  gsZones: 0x70, gsNumPlayer: 0x80, gsMaxPlayer: 0x88, // GameScr.zones/numPlayer/maxPlayer (int[])
  ddPanels: [0xd8, 0xe0], // GameCanvas.panel, GameCanvas.panel2 (gz)
  panelIsShow: 0x10,
  ddMenu: 0xd0,        // GameCanvas.menu (Menu)
  menuShow: 0x10,      // Menu.showMenu
  vtSwitchToMe: 0x178, // vtable slot 4 của mScreen: switchToMe() (fn, MethodInfo* ở +8)
  bhMyChar: 0xa8,      // Char.myCharz()
  hxInstance: 0x0,     // Service.gI()
  // instance fields
  vecList: 0x10,       // MyVector.ArrayList
  alItems: 0x10, alSize: 0x18,
  bossName: 0x10, bossMap: 0x18, bossMapId: 0x20,
  chCx: 0x6c, chCy: 0x70, chId: 0x90, chHp: 0xd0, chHpFull: 0x108, chName: 0x190, // +0xc8 là KI
  chTypePk: 0x295, chMobFocus: 0x2a8, chFocus: 0x2c8, // +0x2c0 là npcFocus
  chMonkey: 0x5da, chCreateDark: 0x4e0, chDart: 0x4d8, gsLastSkill: 0x1a0, // đã biến khỉ / tạo bóng tối / chiêu đang bay / GameScr.lastSkill
  tplType: 0x28,       // SkillTemplate.type: 1 đánh, 3 tự dùng
  rsAutoPick: 0x40, rsPickOthers: 0x41, rsPickFar: 0x42, // Mod.XMAP.rs: Tự động nhặt / nhặt đồ người khác / nhặt xa
  ruPickList: 0x30,    // Mod.XMAP.ru: List<ItemMap> MOD đang nhặt (List: _size +0x18)
  chMySkill: 0x230, chSkillVecs: [0x218, 0x220, 0x228], // Char.myskill, các MyVector có thể chứa Skill
  skTemplate: 0x10, skCoolDown: 0x28, skLastUse: 0x30, skManaUse: 0x44, tplId: 0x10, tplName: 0x18, tplManaType: 0x24, // Skill(if) / SkillTemplate(il)
  chKiFull: 0x110,
  chStatus: 0x88, chMeDead: 0x5de, // statusMe (14 = chết), meDead - giống fg.cng (tự hồi sinh của MOD)
};

function api(name, ret, args) { return new NativeFunction(mod.getExportByName(name), ret, args); }
const il2cpp_domain_get = api('il2cpp_domain_get', 'pointer', []);
const il2cpp_domain_get_assemblies = api('il2cpp_domain_get_assemblies', 'pointer', ['pointer', 'pointer']);
const il2cpp_assembly_get_image = api('il2cpp_assembly_get_image', 'pointer', ['pointer']);
const il2cpp_image_get_name = api('il2cpp_image_get_name', 'pointer', ['pointer']);
const il2cpp_class_from_name = api('il2cpp_class_from_name', 'pointer', ['pointer', 'pointer', 'pointer']);
const il2cpp_runtime_class_init = api('il2cpp_runtime_class_init', 'void', ['pointer']);
const il2cpp_gchandle_new = api('il2cpp_gchandle_new', 'uint32', ['pointer', 'int']);

const xmapStart = new NativeFunction(base.add(RVA.xmapStart), 'void', ['int', 'pointer']);
const changeZone = new NativeFunction(base.add(RVA.changeZone), 'void', ['pointer', 'int', 'int', 'pointer']);
const charMove = new NativeFunction(base.add(RVA.charMove), 'void', ['pointer', 'pointer']);
const panelHide = new NativeFunction(base.add(RVA.panelHide), 'void', ['pointer', 'pointer']);
const openZoneUI = new NativeFunction(base.add(RVA.openZoneUI), 'void', ['pointer', 'pointer']);
const reviveHere = new NativeFunction(base.add(RVA.reviveHere), 'void', ['pointer', 'pointer']);
const returnHome = new NativeFunction(base.add(RVA.returnHome), 'void', ['pointer', 'pointer']);
const useSkillNotFocus = new NativeFunction(base.add(RVA.useSkillNotFocus), 'void', ['pointer', 'pointer', 'pointer']);
const selectSkillSrv = new NativeFunction(base.add(RVA.selectSkillSrv), 'void', ['pointer', 'int', 'pointer']);
const teleportTo = new NativeFunction(base.add(RVA.teleport), 'void', ['int', 'int', 'pointer']);
const focusTo = new NativeFunction(base.add(RVA.focusTo), 'void', ['pointer', 'pointer', 'pointer']);
const openNpcMenu = new NativeFunction(base.add(RVA.openNpcMenu), 'void', ['pointer', 'int', 'pointer']);
const menuClose = new NativeFunction(base.add(RVA.menuClose), 'void', ['pointer', 'pointer']);
const chatPopupPerform = new NativeFunction(base.add(RVA.chatPopupPerform), 'void', ['pointer', 'int', 'pointer', 'pointer']);
const modInstance = new NativeFunction(base.add(RVA.modInstance), 'pointer', ['pointer']);
const modAction = new NativeFunction(base.add(RVA.modAction), 'void', ['pointer', 'int', 'pointer', 'pointer']);

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
for (const full of ['fq', 'fg', 'jb', 'dg', 'bh', 'hx', 'j', 'dd', 'Mod.XMAP.rv', 'Mod.XMAP.rs', 'Mod.XMAP.ru', 'if', 'fa', 'bj']) {
  const dot = full.lastIndexOf('.');
  const ns = dot < 0 ? '' : full.slice(0, dot), name = full.slice(dot + 1);
  const k = il2cpp_class_from_name(image, Memory.allocUtf8String(ns), Memory.allocUtf8String(name));
  if (k.isNull()) throw new Error('Thiếu class ' + name + ' - client khác phiên bản?');
  K[name] = k;
}

// ---- đọc dữ liệu game ----
function statics(k) { return k.add(0xb8).readPointer(); }
function str(p) { return p.isNull() ? '' : p.add(0x14).readUtf16String(p.add(0x10).readS32()); }
function vecItems(vec) {
  if (vec.isNull()) return [];
  const al = vec.add(OFF.vecList).readPointer();
  if (al.isNull()) return [];
  const n = al.add(OFF.alSize).readS32();
  const arr = al.add(OFF.alItems).readPointer();
  const out = [];
  for (let i = 0; i < n; i++) { const e = arr.add(0x20 + 8 * i).readPointer(); if (!e.isNull()) out.push(e); }
  return out;
}
function myChar() { return statics(K.bh).add(OFF.bhMyChar).readPointer(); }
function mapId() { return statics(K.jb).add(OFF.jbMapId).readS32(); }
function mapName() { return str(statics(K.jb).add(OFF.jbMapName).readPointer()); }
function zoneId() { return statics(K.jb).add(OFF.jbZoneId).readS32(); }
function xmapRunning() { il2cpp_runtime_class_init(K.rv); return statics(K.rv).add(OFF.rvXmapRunning).readU8() !== 0; }
function service() { return statics(K.hx).add(OFF.hxInstance).readPointer(); }
function bossNotices() {
  return vecItems(statics(K.fq).add(OFF.fqBossList).readPointer()).map(e => ({
    ptr: e.toString(), name: str(e.add(OFF.bossName).readPointer()),
    map: str(e.add(OFF.bossMap).readPointer()), mapId: e.add(OFF.bossMapId).readS32(),
  }));
}
// Quay về màn hình chơi chính (đóng màn hình VQMM / cửa hàng / các bảng đang mở)
function showGameScr() {
  const menu = statics(K.dd).add(OFF.ddMenu).readPointer();
  if (!menu.isNull()) menu.add(OFF.menuShow).writeU8(0);
  for (const off of OFF.ddPanels) {
    const panel = statics(K.dd).add(off).readPointer();
    if (!panel.isNull() && panel.add(OFF.panelIsShow).readU8()) panelHide(panel, NULL);
  }
  const scr = statics(K.dg).add(OFF.dgInstance).readPointer();
  if (scr.isNull()) return;
  const klass = scr.readPointer();
  const fn = klass.add(OFF.vtSwitchToMe).readPointer();
  const mi = klass.add(OFF.vtSwitchToMe + 8).readPointer();
  new NativeFunction(fn, 'void', ['pointer', 'pointer'])(scr, mi);
}
// Danh sách khu do server trả về sau openUIZone: GameScr.zones / numPlayer / maxPlayer
function intArray(p) {
  if (p.isNull()) return [];
  const n = p.add(0x18).readS32(), out = [];
  for (let i = 0; i < n; i++) out.push(p.add(0x20 + 4 * i).readS32());
  return out;
}
function gameScr() { return statics(K.dg).add(OFF.dgInstance).readPointer(); }
function zoneArrayPtr() { const g = gameScr(); return g.isNull() ? NULL : g.add(OFF.gsNumPlayer).readPointer(); }
function zoneList() {
  const g = gameScr();
  if (g.isNull()) return [];
  const ids = intArray(g.add(OFF.gsZones).readPointer());
  const num = intArray(g.add(OFF.gsNumPlayer).readPointer());
  const max = intArray(g.add(OFF.gsMaxPlayer).readPointer());
  return ids.map((id, i) => ({ id, num: num[i] || 0, max: max[i] || 0 }));
}
function hpPct(c) {
  const full = c.add(OFF.chHpFull).readS64().toNumber();
  return full > 0 ? (c.add(OFF.chHp).readS64().toNumber() * 100) / full : 100;
}
// Khu để chạy trốn: vắng nhất, khác khu boss
function escapeZone(avoid) {
  let zones = zoneList();
  if (!zones.length) zones = Array.from({ length: cfg.maxZone }, (_, id) => ({ id, num: 0, max: 0 }));
  const cand = zones.filter(z => z.id !== avoid && !(z.max > 0 && z.num >= z.max));
  cand.sort((a, b) => a.num - b.num || a.id - b.id);
  return cand.length ? cand[0].id : (avoid + 1) % cfg.maxZone;
}
function canChangeZone(now) { return now - S.lastZoneAt >= cfg.zoneDelayMs; }
function requestZone(z, now) {
  const svc = service();
  if (svc.isNull()) return false;
  showGameScr();
  changeZone(svc, z, -1, NULL);
  S.lastZoneAt = now;
  return true;
}

// Khu kế tiếp: đông người trước, bỏ qua khu đã dò và khu đầy
function nextZone() {
  let zones = zoneList();
  if (!zones.length) zones = Array.from({ length: cfg.maxZone }, (_, id) => ({ id, num: 0, max: 0 }));
  const cand = zones.filter(z => !S.visited.has(z.id) && !(z.max > 0 && z.num >= z.max));
  cand.sort((a, b) => b.num - a.num || a.id - b.id);
  S.zoneInfo = cand.length ? `${cand[0].num} người, còn ${cand.length} khu` : '';
  return cand.length ? cand[0].id : -1;
}
function charsInMap() { return vecItems(statics(K.dg).add(OFF.dgCharInMap).readPointer()); }
function charInfo(c) {
  return { name: str(c.add(OFF.chName).readPointer()), id: c.add(OFF.chId).readS32(),
           hp: c.add(OFF.chHp).readS64().toNumber(), x: c.add(OFF.chCx).readS32(), y: c.add(OFF.chCy).readS32(),
           pk: c.add(OFF.chTypePk).readS8() };
}

// ---- cấu hình & trạng thái ----
let cfg = {
  enabled: false,
  clusters: [],        // [{name, enabled, members: ['số 4', ...]}]
  maxZone: 15,         // dò khu 0..maxZone-1
  zoneDelayMs: 15000,  // server chặn đổi khu ~12-13s tính từ lần gửi trước; gửi dồn sẽ bị kick
  zoneLoadMs: 2500,    // chờ tải nhân vật sau khi sang khu mới
  zoneTimeoutMs: 5000, // quá thời gian này mà khu không đổi = bị từ chối / khu không tồn tại
  arriveDelayMs: 2500, // chờ sau khi tới map
  waitNextMs: 10000,   // khu hết boss thì chờ thêm (boss kế tiếp / biến hình) rồi mới coi là xong cụm
  teleport: true,      // dịch chuyển áp sát boss
  xmapRetryMs: 90000,  // XMAP quá lâu chưa tới thì gọi lại
  badMapMs: 600000,    // map XMAP không tới được: bỏ qua trong 10 phút
  questMode: false,    // tự động làm nhiệm vụ (bật/tắt qua rpc setQuestMode)
  fleeHpPct: 0,        // đang đánh mà HP dưới mức này (%) thì đổi khu chạy trốn (0 = tắt: đánh tới cùng)
  resumeHpPct: 90,     // hồi HP tới mức này (%) thì quay lại khu boss đánh tiếp
  autoRevive: true,          // chết khi đang săn thì tự hồi sinh tại chỗ (server trừ ngọc/vàng)
  reviveDelayMs: 3000,       // chờ sau khi chết rồi mới gửi hồi sinh
  reviveRetryMs: 6000,       // gửi lại nếu chưa sống lại
  reviveAttemptsPerDeath: 3, // hồi sinh tại chỗ không được sau số lần này thì về nhà
  reviveMaxPerTarget: 0,     // 0 = hồi sinh tới khi hạ hết cụm boss; >0: quá số lần thì về nhà, bỏ mục tiêu
  lootMaxMs: 12000,          // nhặt đồ boss rơi tối đa bao lâu
  useBuffSkills: true,       // đang đánh boss thì tự dùng skill hỗ trợ khi hết hồi chiêu
  // ID template skill (chuẩn NRO) hoặc tên skill; nhân vật chỉ có skill của hành tinh mình
  buffSkills: [6, 12, 13],   // 6 Thái Dương Hạ San (TĐ), 12 Đẻ trứng (Namếc), 13 Biến khỉ/Biến hình (Xayda)
};
const S = { state: 'IDLE', cluster: null, targetMap: -1, targetName: '', zone: 0, t: 0, lastMove: 0,
            xmapTries: 0, done: new Set(), badMaps: new Map(), log: [], lastStatus: 0, lastSeen: 0 };

function norm(s) { return s.toLowerCase().normalize('NFC').trim(); }
// "63-83" hoặc 45 -> kiểm tra mapId có nằm trong danh sách không
function inMapList(list, id) {
  return list.some(m => {
    if (typeof m === 'number') return m === id;
    const [a, b] = String(m).split('-').map(Number);
    return b === undefined || isNaN(b) ? a === id : id >= a && id <= b;
  });
}
function clusterAllowsMap(c, id) {
  if (c.maps && c.maps.length && !inMapList(c.maps, id)) return false;
  if (c.excludeMaps && c.excludeMaps.length && inMapList(c.excludeMaps, id)) return false;
  return true;
}
// Tên boss khớp thành viên cụm: chính xác (không phân biệt hoa thường);
// "Fide Đại Ca *" khớp "Fide Đại Ca 1/2/3" nhưng không khớp "Fide Vàng"
function memberMatches(m, n) {
  const k = norm(m);
  if (!k.endsWith('*')) return n === k;
  const prefix = k.slice(0, -1).trim();
  return n === prefix || n.startsWith(prefix + ' ');
}
function clusterOf(name, id) {
  const n = norm(name);
  for (const c of cfg.clusters) {
    if (!c.enabled || !clusterAllowsMap(c, id)) continue;
    if (c.members.some(m => memberMatches(m, n))) return c;
  }
  return null;
}
function isMember(cluster, name) {
  const n = norm(name);
  return cluster.members.some(m => memberMatches(m, n));
}
function log(msg) { S.log.push(msg); send({ type: 'log', msg }); }
function setState(st, extra) { S.state = st; S.t = Date.now(); if (extra) log(extra); }

function aliveBossesHere() {
  if (!S.cluster) return [];
  const out = [];
  for (const c of charsInMap()) {
    const info = charInfo(c);
    if (info.id >= 0 || info.hp <= 0) continue;
    if (isMember(S.cluster, info.name)) out.push({ c, info });
  }
  return out;
}

// Báo GUI tên boss chưa thuộc cụm nào (để người dùng bổ sung vào boss_clusters.json)
function reportNewBossNames() {
  if (!S.seenNames) S.seenNames = new Set();
  for (const b of bossNotices()) {
    const n = norm(b.name);
    if (!n || S.seenNames.has(n)) continue;
    S.seenNames.add(n);
    if (!cfg.clusters.some(c => c.members.some(m => memberMatches(m, n)))) send({ type: 'unknownBoss', name: b.name, map: b.map, mapId: b.mapId });
  }
}

function pickTarget() {
  // thông báo mới được thêm vào cuối danh sách -> duyệt từ mới nhất về cũ nhất
  for (const b of bossNotices().reverse()) {
    if (S.done.has(b.ptr) || b.mapId <= 0) continue;
    if (Date.now() < (S.badMaps.get(b.mapId) || 0)) continue;
    const c = clusterOf(b.name, b.mapId);
    if (!c) continue;
    S.cluster = c; S.targetMap = b.mapId; S.targetName = b.name; S.noticePtr = b.ptr;
    S.zone = -1; S.xmapTries = 0; S.zoneReq = -1; S.lastZoneAt = 0; S.retryZone = -1;
    S.sameFails = 0; S.totalFails = 0; S.visited = new Set(); S.listZone = -1; S.zoneInfo = '';
    S.bossZone = -1; S.revivesThisTarget = 0;
    return b;
  }
  return null;
}

// Thả mục tiêu đang khóa và tắt tự đánh (để không đánh quái lung tung khi XMAP)
function releaseTarget() {
  const me = myChar();
  if (!me.isNull()) me.add(OFF.chFocus).writePointer(NULL);
  statics(K.fg).add(OFF.fgAutoAttack).writeU8(0);
}

// Các tính năng MOD tự kéo nhân vật đi / tự đổi mục tiêu: lưu khi bật săn, giữ tắt khi săn, trả lại khi tắt săn
const MOD_FLAGS = [['fg', 'fgFocusBoss'], ['fg', 'fgKeepFocus'], ['rs', 'rsKillMobs'], ['rs', 'rsKillChars'], ['rs', 'rsGoback'],
  ['rs', 'rsAutoPick'], ['rs', 'rsPickOthers'], ['rs', 'rsPickFar'], ['dg', 'dgAutoPlay']];
function modFlag(cls, name) { return statics(K[cls]).add(OFF[name]); }
function saveModFlags() {
  S.modSaved = MOD_FLAGS.map(([c, n]) => modFlag(c, n).readU8());
  S.locateSaved = statics(K.fg).add(OFF.fgLocateTarget).readPointer();
  if (!S.locateSaved.isNull()) il2cpp_gchandle_new(S.locateSaved, 0); // giữ chuỗi gốc khỏi bị GC dọn trong lúc thay bằng chuỗi rỗng
}
function restoreModFlags() {
  if (!S.modSaved) return;
  MOD_FLAGS.forEach(([c, n], i) => modFlag(c, n).writeU8(S.modSaved[i]));
  statics(K.fg).add(OFF.fgLocateTarget).writePointer(S.locateSaved);
  S.modSaved = null;
}
function quietMod() {
  const set = (c, n, v) => modFlag(c, n).writeU8(v);
  ['fgFocusBoss', 'rsKillMobs', 'rsKillChars', 'rsGoback', 'dgAutoPlay'].forEach(n => set(n.startsWith('fg') ? 'fg' : n.startsWith('rs') ? 'rs' : 'dg', n, 0));
  const loot = S.state === 'LOOT';
  set('rs', 'rsAutoPick', loot ? 1 : 0);  // tự nhặt chỉ trong bước nhặt đồ (lúc đánh nó kéo nhân vật khỏi boss)
  set('rs', 'rsPickFar', loot ? 1 : 0);
  set('rs', 'rsPickOthers', 0);           // không thử nhặt đồ của người khác (tốn tới 20 lần thử mỗi món)
  set('fg', 'fgKeepFocus', S.state === 'FIGHT' ? 1 : 0);
  // thông báo boss trùng tên "Định vị" làm MOD tự XMAP giữa chừng -> thay bằng chuỗi rỗng (null làm menu MOD lỗi)
  const strK = base.add(OFF.stringEmptySlot).readPointer();
  if (!strK.isNull() && (strK.toUInt32() & 1) === 0) statics(K.fg).add(OFF.fgLocateTarget).writePointer(strK.add(0xb8).readPointer().readPointer());
}

function startLoot(now) {
  releaseTarget();
  S.lootEmpty = 0; S.lastLootPoll = 0;
  setState('LOOT', 'Hết boss trong khu, nhặt đồ');
}

function finishTarget(reason) {
  releaseTarget();
  if (S.noticePtr) S.done.add(S.noticePtr);
  // các thông báo khác của cùng cụm trên cùng map cũng coi như đã xử lý
  if (S.cluster) for (const b of bossNotices()) if (b.mapId === S.targetMap && isMember(S.cluster, b.name)) S.done.add(b.ptr);
  log(`Xong ${S.cluster ? S.cluster.name : ''}: ${reason}`);
  S.cluster = null; S.targetMap = -1; S.noticePtr = null;
  setState('IDLE');
}

// Skill của nhân vật: MyVector đầu tiên trong Char chứa object kiểu Skill(if)
function mySkills(me) {
  for (const off of OFF.chSkillVecs) {
    const items = vecItems(me.add(off).readPointer());
    if (items.length && items[0].readPointer().equals(K['if'])) return items;
  }
  return [];
}
function skillTpl(sk) { return sk.isNull() ? NULL : sk.add(OFF.skTemplate).readPointer(); }
// Skill đánh hợp lệ cho ak của MOD: type 1, không phải 10/11 (MOD bỏ qua 2 skill này)
function isAttackSkill(sk) {
  const t = skillTpl(sk);
  if (t.isNull()) return false;
  const id = t.add(OFF.tplId).readS8();
  return t.add(OFF.tplType).readS32() === 1 && id !== 10 && id !== 11;
}
function attackSkillOf(me) {
  const cur = me.add(OFF.chMySkill).readPointer();
  if (isAttackSkill(cur)) S.attackSkill = cur;
  if (S.attackSkill && !S.attackSkill.isNull()) return S.attackSkill;
  return mySkills(me).find(isAttackSkill) || NULL;
}
// Chọn skill đánh như MOD tự luyện: gán myskill + báo server (doSelectSkill bị bỏ qua lúc đang diễn chiêu)
function restoreAttackSkill(me, gs, atk) {
  if (atk.isNull()) return;
  me.add(OFF.chMySkill).writePointer(atk);
  gs.add(OFF.gsLastSkill).writePointer(atk);
  const svc = service();
  if (!svc.isNull()) selectSkillSrv(svc, skillTpl(atk).add(OFF.tplId).readS8(), NULL);
}
// Dùng 1 skill tự dùng (TDHS/Đẻ trứng/Biến khỉ...) đã hết hồi chiêu, rồi chọn lại skill đánh cho ak
function useBuffSkill(me, now, only) {
  if (!only && (!cfg.useBuffSkills || !cfg.buffSkills.length || now - (S.lastBuffTry || 0) < 1000)) return;
  S.lastBuffTry = now;
  const gs = gameScr();
  if (gs.isNull() || !me.add(OFF.chDart).readPointer().isNull() || me.add(OFF.chCreateDark).readU8()) return;
  // đang bị khóa (choáng/trói...) thì game không dùng skill nhưng vẫn đổi skill -> bỏ qua
  if (me.add(0x5f9).readU8() || me.add(0x5fb).readU8() || me.add(0x5fc).readU8()) return;
  const sks = statics(K.dg).add(0xa0).readPointer(); // GameScr.sks: bảng hiệu ứng skill, skillId vượt bảng -> game ném lỗi
  if (sks.isNull()) return;
  const sksLen = sks.add(0x18).readS32();
  const ki = me.add(0xc8).readS64().toNumber();
  for (const sk of mySkills(me)) {
    const tpl = skillTpl(sk);
    if (tpl.isNull() || tpl.add(OFF.tplType).readS32() !== 3) continue;
    const name = str(tpl.add(OFF.tplName).readPointer());
    const tid = tpl.add(OFF.tplId).readS8();
    if (!(only ? [only] : cfg.buffSkills).some(b => (typeof b === 'number' ? b === tid : norm(name).indexOf(norm(b)) >= 0))) continue;
    const last = sk.add(OFF.skLastUse).readS64().toNumber();
    if (now - last < sk.add(OFF.skCoolDown).readS32() + 300) continue;
    const mana = sk.add(OFF.skManaUse).readS32(); // manaType 1 = % KI tối đa
    const need = tpl.add(OFF.tplManaType).readS32() === 1 ? me.add(OFF.chKiFull).readS64().toNumber() * mana / 100 : mana;
    if (ki < need) continue;
    if (tid === 13 && me.add(OFF.chMonkey).readS8() !== 0) continue; // đang biến khỉ rồi
    if (sk.add(0x18).readS16() >= sksLen) continue;
    const atk = attackSkillOf(me);
    me.add(OFF.chMySkill).writePointer(sk); // doUseSkillNotFocus kiểm tra KI theo Char.myskill
    useSkillNotFocus(gs, sk, NULL);
    restoreAttackSkill(me, gs, atk);      // luôn chọn lại skill đánh, kể cả khi dùng hụt
    if (sk.add(OFF.skLastUse).readS64().toNumber() !== last) { log('Dùng skill ' + name); return; }
  }
}

// Khóa mục tiêu, bật tự đánh (ak) và áp sát
function attack(me, t, now) {
  me.add(OFF.chMobFocus).writePointer(NULL);
  me.add(OFF.chFocus).writePointer(t.c);
  statics(K.fg).add(OFF.fgAutoAttack).writeU8(1);
  if (cfg.teleport && now - S.lastMove > 400) {
    const dx = Math.abs(me.add(OFF.chCx).readS32() - t.info.x);
    const dy = Math.abs(me.add(OFF.chCy).readS32() - t.info.y);
    if (dx > 40 || dy > 40) {
      me.add(OFF.chCx).writeS32(t.info.x);
      me.add(OFF.chCy).writeS32(t.info.y);
      const svc = service();
      if (!svc.isNull()) charMove(svc, NULL);
      S.lastMove = now;
    }
  }
}

function handleDeath(now) {
  if (!S.dead) {
    S.dead = true; S.deadSince = now; S.reviveAttempts = 0; S.lastReviveAt = 0; S.wentHome = false;
    releaseTarget();
    log(cfg.autoRevive ? 'Nhân vật đã chết' : 'Nhân vật đã chết, tạm dừng chờ hồi sinh (tự hồi sinh đang tắt)');
  }
  if (!cfg.autoRevive || S.wentHome) return;
  if (now - S.deadSince < cfg.reviveDelayMs || now - S.lastReviveAt < cfg.reviveRetryMs) return;
  const svc = service();
  if (svc.isNull()) return;
  const tooMany = S.cluster && cfg.reviveMaxPerTarget > 0 && (S.revivesThisTarget || 0) >= cfg.reviveMaxPerTarget;
  // không có mục tiêu (chết lúc đang chờ / đang đi) thì về nhà miễn phí, khỏi tốn ngọc/vàng
  if (!S.cluster || tooMany || S.reviveAttempts >= cfg.reviveAttemptsPerDeath) {
    S.wentHome = true; S.lastReviveAt = now;
    returnHome(svc, NULL);
    log(!S.cluster ? 'Chết khi chưa có mục tiêu, về nhà (miễn phí)'
      : tooMany ? `Đã hồi sinh ${S.revivesThisTarget} lần cho mục tiêu này, về nhà và bỏ mục tiêu`
        : 'Hồi sinh tại chỗ không được, về nhà rồi quay lại đánh tiếp');
    if (tooMany) finishTarget('chết quá nhiều lần');
    return;
  }
  S.reviveAttempts++; S.lastReviveAt = now;
  reviveHere(svc, NULL);
  log(`Hồi sinh tại chỗ (lần thử ${S.reviveAttempts})`);
}

function handleRevived() {
  S.dead = false;
  const inPlace = S.reviveAttempts > 0 && !S.wentHome;
  if (inPlace) { S.revivesThisTarget = (S.revivesThisTarget || 0) + 1; S.totalRevives = (S.totalRevives || 0) + 1; }
  const cap = cfg.reviveMaxPerTarget > 0 ? `/${cfg.reviveMaxPerTarget}` : '';
  log(inPlace ? `Đã hồi sinh tại chỗ (lần ${S.revivesThisTarget}${cap} cho mục tiêu này)` : 'Đã sống lại, săn tiếp');
  if (S.state === 'IDLE') return;
  if (mapId() === S.targetMap) setState(S.bossZone >= 0 ? 'RETURN' : 'SCAN');
  else { setState('TRAVEL'); S.xmapAt = 0; S.xmapTries = 0; }
}


// ======================= TỰ ĐỘNG LÀM NHIỆM VỤ =======================
function strArray(p) {
  if (p.isNull()) return [];
  const n = p.add(0x18).readS32(), o = [];
  for (let i = 0; i < n; i++) { const e = p.add(0x20 + 8 * i).readPointer(); o.push(e.isNull() ? null : str(e)); }
  return o;
}
function intArrayAt(p, size) {
  if (p.isNull()) return [];
  const n = p.add(0x18).readS32(), o = [];
  for (let i = 0; i < n; i++) o.push(size === 2 ? p.add(0x20 + 2 * i).readS16() : p.add(0x20 + 4 * i).readS32());
  return o;
}
// Nhiệm vụ hiện tại: tên bước, NPC/map đích, số lượng cần và tiến độ
function readQuest(me) {
  const t = me.add(OFF.chTask).readPointer();
  if (t.isNull()) return null;
  const step = t.add(OFF.tkStep).readS32();
  const titles = strArray(t.add(OFF.tkTitles).readPointer());
  const counts = intArrayAt(t.add(OFF.tkCounts).readPointer(), 2);
  const npcs = intArray(statics(K.dg).add(OFF.dgTaskNpc).readPointer());
  const maps = intArray(statics(K.dg).add(OFF.dgTaskMap).readPointer());
  const q = { id: t.add(OFF.tkId).readS16(), step, total: titles.length, progress: t.add(OFF.tkProgress).readS16() };
  if (step < 0 || step >= titles.length) return Object.assign(q, { done: true, title: '' });
  let title = null;
  for (let i = step; i >= 0 && !title; i--) title = titles[i]; // bước ẩn dùng tên bước trước nó
  return Object.assign(q, { title: title || '', npc: step < npcs.length ? (npcs[step] << 24 >> 24) : -1,
    map: step < maps.length ? maps[step] : -1, need: step < counts.length ? counts[step] : -1 });
}
function findNpc(tpl) {
  for (const n of vecItems(statics(K.dg).add(OFF.dgNpcs).readPointer())) {
    const t = n.add(OFF.npcTemplate).readPointer();
    if (!t.isNull() && t.add(OFF.tplNpcId).readS32() === tpl && !n.add(OFF.npcHide).readU8()) return n;
  }
  return NULL;
}
function mobTemplateName(id) {
  const arr = statics(K.fa).readPointer();
  if (arr.isNull() || id < 0 || id >= arr.add(0x18).readS32()) return '';
  const t = arr.add(0x20 + 8 * id).readPointer();
  return t.isNull() ? '' : str(t.add(OFF.mobTplName).readPointer());
}
// Loại quái của bước "Đánh 10 khủng long": tên quái dài nhất xuất hiện trong câu nhiệm vụ (trong các quái ở map hiện tại)
function questMobTemplate(title) {
  const t = norm(title);
  let best = -1, bestLen = 0;
  for (const m of vecItems(statics(K.dg).add(OFF.dgMobs).readPointer())) {
    const id = m.add(OFF.mobTemplateId).readS32();
    const n = norm(mobTemplateName(id));
    if (n && n.length > bestLen && t.indexOf(n) >= 0) { best = id; bestLen = n.length; }
  }
  return best;
}
function anyMobOf(tpl) {
  return vecItems(statics(K.dg).add(OFF.dgMobs).readPointer()).find(m => m.add(OFF.mobTemplateId).readS32() === tpl) || NULL;
}
function bossNameOf(title) {
  const m = /^(tiêu diệt|diệt|đánh bại|hạ gục|hạ)\s+(.+)$/i.exec(title.trim());
  return m ? m[2].trim() : null;
}
function classifyStep(q) {
  if (q.done) return 'DONE';
  if (q.npc >= 0) return 'TALK';
  if (q.need > 1) return 'KILL';
  if (bossNameOf(q.title)) return 'BOSS';
  if (q.map >= 0) return 'GOTO';
  return 'UNKNOWN';
}
// Đóng khung chat / hộp thoại server / menu còn treo
function closeDialogs(now) {
  const bjS = statics(K.bj);
  const cur = bjS.add(OFF.bjCurr).readPointer();
  if (!cur.isNull()) { bjS.add(OFF.bjPerformDelay).writeS32(0); chatPopupPerform(cur, 8000, NULL, NULL); return true; }
  const srv = bjS.add(OFF.bjServer).readPointer();
  if (!srv.isNull()) { chatPopupPerform(srv, 1001, NULL, NULL); return true; }
  statics(K.bh).add(OFF.bhLockKey).writeU8(0);
  return false;
}
// Menu NPC đang hiện: chọn mục liên quan nhiệm vụ, không có thì đóng
const QUEST_MENU_WORDS = ['nhiệm vụ', 'nhận', 'đồng ý', 'báo cáo', 'hoàn thành', 'ok'];
function handleNpcMenu() {
  const menu = statics(K.dd).add(OFF.ddMenu).readPointer();
  if (menu.isNull() || !menu.add(OFF.menuShow).readU8()) return false;
  const items = vecItems(menu.add(OFF.menuItems).readPointer());
  const caps = items.map(c => {
    const sub = strArray(c.add(OFF.cmdSubCaption).readPointer()).filter(x => x);
    return norm((sub.length ? sub.join(' ') : str(c.add(OFF.cmdCaption).readPointer())).replace(/\n/g, ' '));
  });
  let pick = -1;
  for (const w of QUEST_MENU_WORDS) { pick = caps.findIndex(c => c.indexOf(w) >= 0); if (pick >= 0) break; }
  menu.add(OFF.menuSelected).writeS32(pick >= 0 ? pick : 0);
  menu.add(OFF.menuCancel).writeU8(0);
  menu.add(OFF.menuPerformOnClose).writeU8(pick >= 0 ? 1 : 0); // không có mục phù hợp -> chỉ đóng menu
  menuClose(menu, NULL);
  log(pick >= 0 ? `Chọn "${caps[pick]}"` : `Menu không có mục nhiệm vụ (${caps.join(' | ')}), đóng`);
  return true;
}
function stopKillMobs() {
  const rs = statics(K.rs);
  rs.add(OFF.rsKillMobs).writeU8(0);
  if (Q.killTpl >= 0) { modAction(modInstance(NULL), 18, NULL, NULL); Q.killTpl = -1; } // xoá danh sách tàn sát
}
function questTravel(map, now) {
  if (map < 0 || mapId() === map) return true;
  if (Q.xmapMap !== map) { Q.xmapMap = map; Q.xmapTries = 0; Q.xmapAt = 0; }
  if (Q.xmapAt === 0 || (!xmapRunning() && now - Q.xmapAt > 8000)) {
    if (Q.xmapTries >= 3) { pauseQuest(`XMAP không tới được map ${map}`); return false; }
    Q.xmapTries++; Q.xmapAt = now;
    showGameScr();
    xmapStart(map, NULL);
    log(`Nhiệm vụ: XMAP tới map ${map}`);
  }
  return false;
}
function pauseQuest(reason) {
  stopKillMobs();
  cfg.questMode = false;
  log('Tạm dừng tự làm nhiệm vụ: ' + reason);
  send({ type: 'questPaused', msg: reason });
}
const Q = { key: '', action: '', t: 0, tries: 0, killTpl: -1, xmapMap: -1, xmapTries: 0, xmapAt: 0, lastPopupAt: 0 };
function questTick(me, now) {
  const q = readQuest(me);
  if (!q) return;
  const key = `${q.id}:${q.step}`;
  if (key !== Q.key) {
    stopKillMobs();
    Q.key = key; Q.action = classifyStep(q); Q.t = now; Q.tries = 0; Q.phase = '';
    log(`Nhiệm vụ ${q.id} bước ${q.step + 1}/${q.total}: ${q.title || '(xong, chờ nhiệm vụ mới)'} [${Q.action}]`);
  }
  Q.info = { id: q.id, step: q.step, total: q.total, title: q.title, action: Q.action, progress: q.progress, need: q.need };
  // khung chat của NPC/server sau mỗi bước: bấm qua cho hết
  if (now - Q.lastPopupAt > 400 && closeDialogs(now)) { Q.lastPopupAt = now; return; }
  switch (Q.action) {
    case 'DONE': return; // chờ server giao nhiệm vụ tiếp theo
    case 'UNKNOWN': pauseQuest(`chưa hỗ trợ bước "${q.title}"`); return;
    case 'BOSS': {
      if (S.state !== 'IDLE') return; // bộ săn boss đang chạy
      const name = bossNameOf(q.title);
      const cluster = { name: 'Nhiệm vụ', enabled: true, members: [name] };
      const here = charsInMap().map(c => ({ c, info: charInfo(c) })).find(x => x.info.id < 0 && x.info.hp > 0 && memberMatches(name, norm(x.info.name)));
      if (here) { S.cluster = cluster; S.targetMap = mapId(); S.targetName = name; S.bossZone = zoneId(); S.revivesThisTarget = 0; S.lastSeen = now; setState('FIGHT', `Nhiệm vụ: đánh ${name} ngay tại khu`); return; }
      const b = bossNotices().reverse().find(x => x.mapId > 0 && memberMatches(name, norm(x.name)) && !S.done.has(x.ptr) && now >= (S.badMaps.get(x.mapId) || 0));
      if (b) {
        S.cluster = cluster; S.targetMap = b.mapId; S.targetName = name; S.noticePtr = b.ptr;
        S.zone = -1; S.xmapTries = 0; S.zoneReq = -1; S.lastZoneAt = 0; S.retryZone = -1; S.sameFails = 0; S.totalFails = 0;
        S.visited = new Set(); S.listZone = -1; S.zoneInfo = ''; S.bossZone = -1; S.revivesThisTarget = 0;
        showGameScr(); setState('TRAVEL', `Nhiệm vụ: săn ${name} tại ${b.map} (map ${b.mapId})`); S.xmapAt = 0;
      } else if (Q.phase !== 'wait') { Q.phase = 'wait'; log(`Nhiệm vụ: chờ ${name} xuất hiện (bật Thông báo BOSS)`); }
      return;
    }
    case 'GOTO': {
      if (!questTravel(q.map, now)) return;
      const hx = me.add(OFF.chHintX).readS16(), hy = me.add(OFF.chHintY).readS16();
      if (hx && hy && Q.phase !== 'hint') { Q.phase = 'hint'; teleportTo(hx, hy, NULL); log('Nhiệm vụ: tới điểm nhấp nháy'); }
      if (now - Q.t > 30000) pauseQuest(`tới map ${q.map} nhưng bước "${q.title}" chưa xong`);
      return;
    }
    case 'TALK': {
      if (!questTravel(q.map, now)) return;
      if (now - Q.t < 1500) return; // chờ map tải xong
      if (Q.phase === 'menu' && now - Q.talkAt < 8000) { if (handleNpcMenu()) Q.talkAt = now - 6000; return; }
      if (Q.tries >= 3) { pauseQuest(`nói chuyện với NPC ${q.npc} 3 lần mà bước "${q.title}" chưa xong`); return; }
      const npc = findNpc(q.npc);
      if (npc.isNull()) { if (now - Q.t > 15000) pauseQuest(`không thấy NPC ${q.npc} ở map ${mapId()}`); return; }
      const menu = statics(K.dd).add(OFF.ddMenu).readPointer();
      if (!menu.isNull() && menu.add(OFF.menuShow).readU8()) { menu.add(OFF.menuCancel).writeU8(0); menu.add(OFF.menuPerformOnClose).writeU8(0); menuClose(menu, NULL); }
      const nx = npc.add(OFF.chCx).readS32(), ny = npc.add(OFF.chCy).readS32();
      if (Math.abs(me.add(OFF.chCx).readS32() - nx) > 40) teleportTo(nx, ny - 1, NULL);
      focusTo(me, npc, NULL);
      const svc = service();
      if (svc.isNull()) return;
      openNpcMenu(svc, q.npc, NULL);
      Q.tries++; Q.phase = 'menu'; Q.talkAt = now;
      const t = npc.add(OFF.npcTemplate).readPointer();
      log(`Nhiệm vụ: nói chuyện với ${str(t.add(OFF.tplNpcName).readPointer())} (lần ${Q.tries})`);
      return;
    }
    case 'KILL': {
      if (!questTravel(q.map, now)) return;
      if (now - Q.t < 1500) return;
      if (Q.killTpl < 0) {
        const tpl = questMobTemplate(q.title);
        const mob = tpl >= 0 ? anyMobOf(tpl) : NULL;
        if (mob.isNull()) { if (now - Q.t > 15000) pauseQuest(`không nhận ra quái cần đánh trong "${q.title}" ở map ${mapId()}`); return; }
        const fz = modInstance(NULL);
        modAction(fz, 18, NULL, NULL);   // xoá danh sách tàn sát (danh sách rỗng = đánh mọi quái)
        modAction(fz, 19, mob, NULL);    // thêm loại quái này + bật Tàn sát
        statics(K.rs).add(OFF.rsAutoPick).writeU8(1); // nhặt đồ nhiệm vụ rơi ra
        Q.killTpl = tpl;
        log(`Nhiệm vụ: tàn sát ${mobTemplateName(tpl)} (${q.progress < 0 ? 0 : q.progress}/${q.need})`);
      }
      return;
    }
  }
}

function tick() {
  const now = Date.now();
  const me = myChar();
  if (me.isNull()) return;

  if (now - S.lastStatus > 500) {
    S.lastStatus = now;
    send({ type: 'status', state: S.state, cluster: S.cluster ? S.cluster.name : '', target: S.targetName,
           targetMap: S.targetMap, map: mapName(), mapId: mapId(), zone: zoneId(), scanZone: S.zone,
           enabled: cfg.enabled, quest: cfg.questMode ? (Q.info || null) : null });
  }
  if (S.testZone !== undefined) {
    const svc = service();
    if (!svc.isNull()) changeZone(svc, S.testZone, -1, NULL);
    S.testZone = undefined;
  }
  if (S.testShow) { showGameScr(); S.testShow = false; }
  if (S.testZoneUI) { const svc = service(); if (!svc.isNull()) openZoneUI(svc, NULL); S.testZoneUI = false; }
  if (S.testAttack) {
    const ta = S.testAttack;
    const c = charsInMap().find(x => charInfo(x).name.indexOf(ta.name) >= 0);
    if (Date.now() > ta.until || !c) {
      me.add(OFF.chFocus).writePointer(NULL);
      statics(K.fg).add(OFF.fgAutoAttack).writeU8(0);
      log(`Test đánh kết thúc (${c ? 'hết giờ' : 'mục tiêu biến mất'})`);
      S.testAttack = null;
    } else {
      const info = charInfo(c);
      attack(me, { c, info }, Date.now());
      if (Date.now() - (ta.lastLog || 0) > 1000) { ta.lastLog = Date.now(); log(`Test: ${info.name} HP ${info.hp} | mình (${me.add(OFF.chCx).readS32()},${me.add(OFF.chCy).readS32()}) mục tiêu (${info.x},${info.y})`); }
    }
  }
  if (S.testSkill) { useBuffSkill(me, Date.now(), S.testSkill); S.testSkill = null; }
  if (S.testAction !== undefined) {
    modAction(modInstance(NULL), S.testAction, NULL, NULL);
    S.testAction = undefined;
  }
  const questBoss = cfg.questMode && Q.action === 'BOSS';
  if (!cfg.enabled && !cfg.questMode) return;

  // luôn bật Thông báo BOSS để có danh sách boss
  statics(K.fq).add(OFF.fqNotifyBoss).writeU8(1);
  if (cfg.enabled || questBoss) quietMod(); // MOD không được kéo nhân vật đi / đổi mục tiêu giữa chừng -> săn lần lượt

  // nhân vật chết: tự hồi sinh (nếu bật) rồi quay lại săn tiếp
  if (me.add(OFF.chHp).readS64().toNumber() <= 0 || me.add(OFF.chMeDead).readU8() || me.add(OFF.chStatus).readS32() === 14) {
    handleDeath(now);
    return;
  }
  if (S.dead) handleRevived();
  if (cfg.questMode && S.state === 'IDLE') questTick(me, now);

  switch (S.state) {
    case 'IDLE': {
      if (cfg.questMode) break; // chế độ nhiệm vụ tự quyết mục tiêu
      reportNewBossNames();
      const b = pickTarget();
      if (b) { showGameScr(); setState('TRAVEL', `Săn cụm ${S.cluster.name}: ${b.name} tại ${b.map} (map ${b.mapId})`); S.xmapAt = 0; }
      break;
    }
    case 'TRAVEL': {
      if (mapId() === S.targetMap) { setState('ARRIVE', `Đã tới ${mapName()}`); break; }
      // gọi lại XMAP nếu nó đã dừng mà chưa tới nơi (bị kẹt/ngắt), hoặc chạy quá lâu
      const stalled = S.xmapAt !== 0 && !xmapRunning() && now - S.xmapAt > 8000;
      if (S.xmapAt === 0 || stalled || now - S.xmapAt > cfg.xmapRetryMs) {
        if (S.xmapTries >= 2) {
          S.badMaps.set(S.targetMap, now + cfg.badMapMs);
          showGameScr();
          finishTarget(`XMAP không tới được map ${S.targetMap}, bỏ qua map này 10 phút`);
          break;
        }
        S.xmapTries++; S.xmapAt = now;
        showGameScr();
        xmapStart(S.targetMap, NULL);
        log(`XMAP tới map ${S.targetMap} (lần ${S.xmapTries})`);
      }
      break;
    }
    case 'ARRIVE':
      // đã biết khu có boss (vừa chết / chạy trốn khỏi map) thì quay thẳng về khu đó
      if (now - S.t > cfg.arriveDelayMs) setState(S.bossZone >= 0 ? 'RETURN' : 'SCAN');
      break;
    case 'SCAN': {
      if (mapId() !== S.targetMap) { setState('TRAVEL'); S.xmapAt = 0; break; }
      if (!S.visited) S.visited = new Set();
      if (S.zoneReq >= 0) {
        // đang chờ server chuyển khu
        if (zoneId() === S.zoneReq) { S.zoneReq = -1; S.sameFails = 0; S.totalFails = 0; S.t = now; break; }
        if (now - S.lastZoneAt < cfg.zoneTimeoutMs) break;
        log(`Không vào được khu ${S.zoneReq}`);
        S.sameFails++; S.totalFails++; S.t = now;
        if (S.sameFails >= 2) { S.visited.add(S.zoneReq); S.sameFails = 0; S.retryZone = -1; }
        else S.retryZone = S.zoneReq; // thử lại đúng khu này một lần nữa
        S.zoneReq = -1;
        if (S.totalFails >= 5) { finishTarget('không đổi được khu'); break; }
      }
      if (now - S.t < cfg.zoneLoadMs) break;
      const here = zoneId();
      if (!S.visited.has(here)) {
        S.visited.add(here);
        // ghi lại các nhân vật không phải người chơi trong khu (để kiểm tra nhận diện boss)
        const npcs = charsInMap().map(charInfo).filter(i => i.id < 0 && i.name && !/đệ tử/i.test(i.name))
          .map(i => `${i.name}(${i.hp})`);
        if (npcs.length) log(`Khu ${here}: ${npcs.join(', ')}`);
      }
      if (aliveBossesHere().length) { S.bossZone = here; setState('FIGHT', `Thấy boss ở khu ${here}`); S.lastSeen = now; break; }
      // xin danh sách khu (số người từng khu) mỗi khi sang khu mới, chờ server trả lời tối đa 3s
      if (S.listZone !== here) {
        S.listZone = here; S.listAt = now; S.listArr = zoneArrayPtr();
        const svc = service();
        if (!svc.isNull()) openZoneUI(svc, NULL);
        break;
      }
      if (zoneArrayPtr().equals(S.listArr) && now - S.listAt < 3000) break;
      if (now - S.lastZoneAt < cfg.zoneDelayMs) break;
      const next = S.retryZone >= 0 ? S.retryZone : nextZone();
      S.retryZone = -1;
      if (next < 0) { finishTarget('đã dò hết khu, không thấy boss'); break; }
      const svc = service();
      if (svc.isNull()) break;
      showGameScr(); // đóng bảng chọn khu nếu server vừa mở ra
      changeZone(svc, next, -1, NULL);
      S.zoneReq = next; S.zone = next; S.lastZoneAt = now;
      log(`Dò khu ${next}${S.zoneInfo ? ` (${S.zoneInfo})` : ''}`);
      break;
    }
    case 'FIGHT': {
      if (mapId() !== S.targetMap) { setState('TRAVEL'); S.xmapAt = 0; break; }
      const bosses = aliveBossesHere();
      if (!bosses.length) {
        if (now - S.lastSeen > cfg.waitNextMs) startLoot(now);
        break;
      }
      S.lastSeen = now;
      const myPct = hpPct(me);
      if (cfg.fleeHpPct > 0 && myPct < cfg.fleeHpPct) {
        S.bossZone = zoneId();
        me.add(OFF.chFocus).writePointer(NULL);
        statics(K.fg).add(OFF.fgAutoAttack).writeU8(0);
        setState('FLEE', `HP còn ${myPct.toFixed(0)}%, đổi khu chạy trốn`);
        break;
      }
      // ưu tiên boss đang bật PK (đang tới lượt đánh)
      bosses.sort((a, b) => (b.info.pk === 5) - (a.info.pk === 5));
      const t = bosses[0];
      if (now - (S.lastFightLog || 0) > 3000) {
        S.lastFightLog = now;
        log(`Đánh ${t.info.name}: HP ${(t.info.hp / 1e6).toFixed(2)}M (${hpPct(t.c).toFixed(1)}%) | mình ${myPct.toFixed(0)}%`);
      }
      attack(me, t, now);
      useBuffSkill(me, now);
      break;
    }
    case 'LOOT': {
      // MOD tự nhặt (chỉ chạy khi XMAP đứng yên): chờ danh sách đang nhặt trống 3 lần liên tiếp
      if (now - S.t < 1500 || now - S.lastLootPoll < 250) break;
      S.lastLootPoll = now;
      const list = statics(K.ru).add(OFF.ruPickList).readPointer();
      S.lootEmpty = (list.isNull() || list.add(0x18).readS32() === 0) ? S.lootEmpty + 1 : 0;
      if (S.lootEmpty >= 3 || now - S.t > cfg.lootMaxMs) finishTarget('đã hạ hết boss và nhặt đồ');
      break;
    }
    case 'FLEE': {
      if (mapId() !== S.targetMap) { setState('TRAVEL'); S.xmapAt = 0; break; }
      if (zoneId() === S.bossZone) {
        if (canChangeZone(now) && requestZone(escapeZone(S.bossZone), now)) log('Đổi khu để chạy trốn');
        break;
      }
      if (hpPct(me) >= cfg.resumeHpPct) setState('RETURN', `HP hồi ${hpPct(me).toFixed(0)}%, quay lại khu ${S.bossZone}`);
      break;
    }
    case 'RETURN': {
      if (mapId() !== S.targetMap) { setState('TRAVEL'); S.xmapAt = 0; break; }
      if (zoneId() !== S.bossZone) {
        if (canChangeZone(now)) requestZone(S.bossZone, now);
        S.t = now;
        break;
      }
      if (now - S.t < cfg.zoneLoadMs) break;
      if (aliveBossesHere().length) { setState('FIGHT', 'Đánh tiếp'); S.lastSeen = now; }
      // danh sách nhân vật trong khu có thể chưa tải xong sau khi hồi sinh / đổi khu
      else if (now - S.t > cfg.zoneLoadMs + cfg.waitNextMs) finishTarget('boss đã bị hạ');
      break;
    }
  }
}

let busy = false;
Interceptor.attach(base.add(RVA.mainFixedUpdate), {
  onEnter() {
    if (busy) return;
    busy = true;
    try {
      tick();
    } catch (e) {
      // không tắt săn: báo lỗi (tối đa 1 lần/5s), bỏ mục tiêu hiện tại rồi chạy tiếp vòng lặp
      const now = Date.now();
      if (!S.lastErrAt || now - S.lastErrAt > 5000) { S.lastErrAt = now; send({ type: 'error', msg: String(e.stack || e) }); }
      try { releaseTarget(); } catch (e2) { /* game đang chuyển màn hình */ }
      S.cluster = null; S.targetMap = -1; S.state = 'IDLE';
    }
    busy = false;
  },
});

rpc.exports = {
  setQuestMode(on) {
    if (on && !cfg.questMode) {
      if (!cfg.enabled) { S.akBefore = statics(K.fg).add(OFF.fgAutoAttack).readU8(); saveModFlags(); }
      Q.key = ''; S.done.clear(); setState('IDLE');
      cfg.questMode = true; log('Bắt đầu tự làm nhiệm vụ');
    } else if (!on && cfg.questMode) {
      cfg.questMode = false; stopKillMobs(); releaseTarget();
      if (!cfg.enabled) { statics(K.fg).add(OFF.fgAutoAttack).writeU8(S.akBefore || 0); restoreModFlags(); }
      S.cluster = null; setState('IDLE', 'Dừng tự làm nhiệm vụ');
    }
    return true;
  },
  setConfig(c) {
    const wasEnabled = cfg.enabled;
    cfg = Object.assign(cfg, c);
    if (!wasEnabled && cfg.enabled) {
      S.akBefore = statics(K.fg).add(OFF.fgAutoAttack).readU8(); // nhớ trạng thái các cờ MOD của người chơi
      saveModFlags();
      S.done.clear(); setState('IDLE', 'Bắt đầu săn');
    }
    if (wasEnabled && !cfg.enabled) {
      if (S.state === 'FIGHT' || S.state === 'RETURN') { const me = myChar(); if (!me.isNull()) me.add(OFF.chFocus).writePointer(NULL); }
      statics(K.fg).add(OFF.fgAutoAttack).writeU8(S.akBefore || 0);
      restoreModFlags();
      S.cluster = null; setState('IDLE', 'Dừng săn');
    }
    return true;
  },
  changeZone(z) { S.testZone = z; return true; },
  showGameScr() { S.testShow = true; return true; },
  openZoneUI() { S.testZoneUI = true; return true; },
  testAttack(name, ms) { S.testAttack = { name, until: Date.now() + ms }; return true; },
  useSkill(name) { S.testSkill = name; return true; },
  modAction(id) { S.testAction = id; return true; },
  // test: săn một mục tiêu ngay tại map hiện tại (không cần thông báo boss)
  huntHere(member, overrides) {
    cfg = Object.assign(cfg, overrides || {}, { enabled: true });
    S.cluster = { name: 'test', enabled: true, members: [member] };
    S.targetMap = mapId(); S.targetName = member; S.noticePtr = null;
    S.zone = -1; S.zoneReq = -1; S.retryZone = -1; S.sameFails = 0; S.totalFails = 0;
    S.visited = new Set(); S.listZone = -1; S.zoneInfo = ''; S.bossZone = -1; S.lastZoneAt = Date.now();
    S.revivesThisTarget = 0;
    S.akBefore = statics(K.fg).add(OFF.fgAutoAttack).readU8();
    setState('SCAN', `Test săn ${member} tại map ${S.targetMap}`);
    return true;
  },
  skip() { if (S.state !== 'IDLE') finishTarget('bỏ qua theo yêu cầu'); return true; },
};
