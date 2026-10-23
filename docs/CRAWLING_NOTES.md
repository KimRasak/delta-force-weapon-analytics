# 《三角洲行动》枪支、零件与实时交易行物价：数据爬取与底层逆向心得

本文档详细记录本仓库（`delta-force-weapon-analytics`）在收集《三角洲行动》全非狙击枪支（62把）、全枪械零件（577件）、全口径弹药（114种）与实时交易行物价过程中的 **数据源发现路径、双通道爬虫架构设计、以及底层解包字段逆向踩坑心得**。

---

## 一、寻找权威数据源的「顺藤摸瓜」路径

如果直接在通用搜索引擎搜索“三角洲行动枪械数据/配件价格”，得到的往往是过期的旧赛季图文攻略或残缺的手工表格。为获取 **100% 完整且随版本更新的客户端底层真值**，我们采用了以下发现链路：

1. **通过 GitHub 开源生态反推上游数据源**：
   - 使用 GitHub 代码搜索（`gh search code`）检索特征组合词（如 `"腾龙" "fireRate"`、`"M250" "armorDamage"`、`"冲锋枪回声消音器"`、`"新式腾龙高速导气箍"`）。
   - 迅速定位到社区正在活跃维护的多个开源项目（如 `Cany-litter/df-ttk` 的 `vue3-refactor` 分支、`mtai000/df_ttk_sim`、`Entropy-Increase-Team/delta-force-plugin`、`orzice/DeltaForceApi` 等）。
   - 从这些项目的自动化脚本与配置文件中，顺藤摸瓜找到了全网最核心的两个上游数据枢纽：
     - **底层机制与零件解包源**：`https://dfttk.com`（三角洲行动 TTK 与数据图鉴站）
     - **实时交易行物价源**：`https://orzice.com`（三角洲数据帝 / 小涛查）

---

## 二、从「无头浏览器模拟点击」到「纯 HTTP 并发直拉」的降维打击

### 心得 1：善用现代站点的 `/llms.txt` 与静态 Manifest 索引
- **传统做法的痛点**：许多第三方工具站是复杂的单页应用（SPA），常规做法是用 Playwright 启动带持久化目录（Persistent Context）的浏览器去逐个点击切换武器、打开弹窗读取价格与属性——不仅跑一轮需要几十分钟，而且极其脆弱。
- **突破口**：在检查 `https://dfttk.com` 首页 `<head>` 标签时，我们发现了站点专门提供的 AI/开发者契约入口：
  - `<link rel="alternate" type="text/plain" href="/llms.txt" />`
  - `<link rel="alternate" type="application/json" href="/ai/context.json" />`
- **全量静态 JSON 仓库直连**：顺着 `/llms.txt` 给出的指引，直接定位到了 **`https://dfttk.com/data/v3/manifest.json`**！
  - 该 Manifest 暴露了当前最新的游戏平衡版本（`dataVersion: "20261015-bd-balance.1"`）以及全站所有结构化静态 JSON 的相对路径：
    1. `catalog/weapons.json`：全部 68 把武器的三模式（烽火 `sol` / 战场 `mp` / 爆破 `bd`）基础战斗属性。
    2. `library/sol.json`：**全部 577 个枪械零件**的完整客户端 SDK 操作指令（`operations`、`mappedOperations`、`damageProfile`、`bulletProfile`、`override` 及 `weaponIds` 适配关系）。
    3. `packs/combat/weapons/{weaponId}.json`：全部 68 把武器的单枪运行时战斗包（包含每个零件在该枪上的精校滑块范围 `tunes` 与非线性响应曲线 `curves`）。
    4. `catalog/ammo.json` & `combat/defense/ammo-interactions.json`：全部 114 种子弹及对 1~6 级护甲的穿透率/破甲率矩阵。
    5. `economy/market-prices.json`：每日自动从 `orzice-work-api` 同步的全物品交易行价格表（含 720 个武器、零件、弹药的 11 位官方 ID 价格映射）。
- **效果对比**：使用 Python 标准库 `urllib.request` + `ThreadPoolExecutor(max_workers=12)` 并发拉取，**无需安装浏览器、无需登录态，仅需 2~10 秒即可拉取全部 68 把武器与 577 个零件的完整客户端级数据**。
- **合规准则**：严格遵循 `dfttk.com/llms.txt` 的字段访问规范，仅读取公开授权用于战斗分析的 `entrypoints` 与 `weaponPacks[weaponId].combat`，绝不读取或暴露 `build` / `sharedBuild` 私有包。

---

## 三、交易行实时价格的「双通道互补」架构

游戏内交易行物价每天甚至每小时都在波动，单一数据源存在覆盖盲区，因此我们在 `scripts/fetch_live_data.py` 中设计了 **双通道互补融合**：

### 1. 通道一：`dfttk.com/data/v3/economy/market-prices.json`（按 11 位官方物品 ID 精准对齐）
- **优势**：直接以游戏内部 11 位物品 ID（如 `18010000038` 腾龙、`13030000111` 幻影后握把）作为 Key，彻底消除了中文简称、空格或符号不一致导致的匹配错误，覆盖了 **575 / 577 个枪械零件** 和全部可交易裸枪。
- **盲区**：有 41 个物品（特别是 `.300BLK` 系列子弹、`12.7x55mm` 系列子弹及部分新赛季特种弹）在该接口中被标记为 `providerCatalogUnavailable`（价格为 `null`）。

### 2. 通道二：`orzice.com/v/ammo` 服务端渲染（SSR HTML）秒级直爬
- **发现**：虽然 `orzice` 的开放平台 API（`/v1/sjz_api/*`）需要申请商业 Token，但其网页端 `https://orzice.com/v/ammo?a=ammo&top=2-2&p={1..9}&grade=-1&n=` 采用的是 **服务端直出渲染（SSR HTML）**！
- **实现**：无需执行页面 Vue/JS 脚本，直接用 5 线程并发请求第 1~9 页 HTML（总耗时仅 **0.8 秒**），用正则提取 `<div class="ui-tname">`（子弹名称）与 `<span class="icon-gold ui-num">`（当前交易行实时价格），一次性抓出全部 **86 种可交易子弹的分钟级实时价格**。
- **名称对齐踩坑与清洗技巧**：
  1. **HTML 实体与特殊空白符**：网页中的 `+` 号（如 `5.7x28mm HT+`）在 SSR HTML 中被编码为 `&#43;`，部分子弹名中间带有不间断空格 `\xa0`（如 `7.62x51mm\xa0Ultra\xa0Nosler`），必须先做实体反转义与空白符归一化。
  2. **`.300BLK` 命名异构**：游戏内 `.300BLK` 的 3/4/5 级弹分别叫 `V-Max`、`BCP-FMJ`、`TAC-TX`，但在 `orzice` 交易行列表里被直接命名为 `.300BLK_3`、`.300BLK_4`、`.300BLK_5`！我们在构建价格映射时增加了 `.300BLK_{penetrationLevel}` 别名键，完美解决了 `.300BLK` 价格匹配问题。
  3. **6级红弹的交易行禁售识别**：`7.62x51mm M61`、`7.62x54R SNB`、`6.8x51mm AP`、`.338 Lap Mag AP`、`.50 BMG` 等 6~7 级红弹在游戏内交易行禁售（仅能通过特勤处制造或局内摸出），脚本自动识别其穿甲等级 `>= 6` 并标注为 `红弹(交易行禁售/仅特勤处制造或局内产出)`，避免误判为爬虫缺失。

---

## 四、底层客户端解包数据逆向的「四大踩坑心得」

拿到原始 SDK 解包 JSON 后，如果直接按字面意思处理字段，会掉入四个极易算错数据的陷阱：

### 踩坑 1：`GRateOfFire` 在底层其实是「射击间隔乘数」而非「射速乘数」！
- **现象**：在解包数据中，提高射速的 `新式腾龙高速导气箍` 词条为 `GRateOfFire (Mult_A) = -0.07`、`QJB201新式高速导气箍` 为 `-0.10`；而降低射速的 `死寂消音器` 词条却是 `GRateOfFire (Mult_A) = +0.15`。
- **真相**：如果把 `GRateOfFire` 当作射速（RPM）乘数去算 `706 * (1 - 0.07)`，高速导气反而变成降射速了！实际上，引擎内部存储的是 **`fireInterval`（两发子弹之间的射击间隔秒数）**，`GRateOfFire` 修改的是射击间隔：
  $$\text{改装后射速 (RPM)} = \frac{60}{\text{原始射击间隔} \times (1 + \text{GRateOfFire})} = \frac{\text{原始射速}}{1 + \text{GRateOfFire}}$$
  例如腾龙原始间隔 `0.085s`（`705.88 RPM`），装高速导气后间隔变为 `0.085 * (1 - 0.07) = 0.07905s`，对应射速 `60 / 0.07905 = 759.0 RPM`，与游戏内靶场实测分毫不差。

### 踩坑 2：区别「value = 0 的无效占位符」与「Initial = 0 的核心机制覆写」
- **现象**：`library/sol.json` 中几乎所有配件都带有 `DisplayAttrValues.2 (Mult_A) = 0` 等大量 `value = 0` 的冗余操作指令。
- **陷阱**：如果简单用 `if op['value'] != 0:` 过滤，会把两类极其关键的 **质变指令** 误删掉：
  1. `FireDelayTime (Initial) = 0`（如 `QJB201新式獠牙短枪管` 和 `QJB201 75发弹匣` 将机枪 50ms 开膛待击延迟覆写为 **0ms**）；
  2. `FireRateMode (Initial) = 0`（如 `SVCH长枪管`、`MK4深空镀铬枪管`、`93R HVK鼬鼠套件` 将开火模式覆写为枚举值 `0`，即 **解锁全自动模式**）。
- **正确过滤条件**：必须写成 `if op['value'] != 0 or op['modifier'] == 'Initial':`，既清除无效的 `+0` 占位符，又完整保留覆写为 `0` 的核心机制变更。

### 踩坑 3：激光镭指/战术手电在同一个零件里有两个互相冲突的 `MainAttrValues.5 (操控速度)`
- **现象**：以 `PEQ-2红色激光镭指` 为例，它的 `operations` 数组里同时存在两条针对 `MainAttrValues.5` 的 `Addend` 指令：一条是 `-4`，另一条是 `+16`（同时还有一条 `MainAttrValues.4 腰射 +12`）。如果直接求和，面板操控会变成常驻 `+12`。
- **真相**：在游戏机制中，第一条 `-4` 是安装镭指后的 **常驻重量惩罚（关闭激光时）**，而第二条 `+16` 是 **开启激光/进入战术据枪姿态时的激活加成**。我们在解析器中专门对同属性多条 `Addend` 进行了分离，分别记录常驻面板值（`-4`）与开启镭指激活值（`开启镭指时:腰射+12/操控+16`）。

### 踩坑 4：面板五维之外的 15 项「隐藏独立乘区」提取
- 许多高价配件（如 `堡垒水平补偿器`、`沙暴垂直补偿器`、`RK-0前握把`、`密令斜角握把`、`共振人体工程握把`、`CR棱镜阻手器`、`枢机稳固枪托`）在面板五维（`MainAttrValues.2~6`）上的加成全是 `0` 或只有 `-1`！
- 如果只爬面板五维，这些顶级配件看起来就像毫无用处的废品。只有深入解析 `operations` 中的引擎底层 Target（`GRecoil_V`、`GRecoil_H`、`GRecoil_VShake`、`GRecoil_HShake`、`GGunkickV/H/Random/Spring`、`GAiming_ADSTime`、`GMovement_ADSSpeed`、`GBullet_OnlyRange`、`CameraSwayBeHitScale`），才能真正还原《三角洲行动》改枪系统的完整数学模型。
