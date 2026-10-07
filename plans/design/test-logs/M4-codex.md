# M4 Codex 真实宿主补测（进行中）

日期2026-10-07，scratch `/tmp/research-tree-codex-20261007-1XA9OP`，新 `rt-test-M4-codex`/独立 `codex-home-M4`，Herdr `rt-codex-m4` / 自建w3:pJ。原生主线程01a11630-2465-7932-a78e-332e0688e167，observed gpt-6-luna/FullAccess/approval never。四已开项目原生permission/model收据保留native-permissions-1158.json；M4新缓存69/69实质构建文件一致（排除运行生成pyc），旧活跃M1/M2/M3缓存如实保留差异、不覆盖。

## 提供夹具与授权边界

此项目预先明示simulation_only：真实本机CPU logistic工作、真实模型/插件MCP/产物/用量；accuracy是确认前冻结公式0.80+0.0025*(seed%3)+(functional_gain?0.01:0)。measured_logistic_accuracy/loss/time仅作诊断，不冒充优化器科研提升；后续独立注册functional_probe用于候选/确认功能，不进入benchmark科研得分。正式研究协议/评审与页面须保留此限制，不预写reviewer结果或GO。首个确认只覆盖根sanity与两基线，方法/候选/独立确认另行具体授权。

提供train/runner/stats/三configs，初版配置仍写toy-v1/旧model，被真实RLD发现；控制器在确认/训练前修正配置身份为toy-functional-sim-v1与exact model字符串，提交实际HEAD a62c358a528549ce023d35736779a04f9a54d4b5。控制器第一次技术提示误写hash，马上保留原话并更正，RLD以git实际值核验，误写值不可用作code_ref。旧临时文档改写引起hash完整性提示，真实RLD正在恢复历史内容并版本化现行材料；不能沿用旧方案执行。prepare保留输入、init完成，尚未confirm/root训练。

## 最新默认独立UI已通过的部分

human-facing codex_cli.py ui与最新安装独立真实UI，全为observed gpt-6-luna/read-only，未提供“省略project”或“confirm是handoff”等技术提示。证据M4-native-ui-proof.json：

- thread01a11638-7dd8-7363-ad0b-abb324cdc60f：模糊根基线图表要求，保存REQ-0001，向用户问必要细节，actions=[]，无RLD转交/确认/执行。
- thread01a11639-acbc-7923-a469-a1b831f2ae82：补充Adam/Momentum、seeds0/1/2、synthetic accuracy百分比、真实train_time_s、SVG路径和simulation_only，复用REQ完整七字段并保留两份原话，仍open/文档version0/actions=[]。回复中的“v2”是助手描述草稿修订，数据库没有提交v2，不能把它计为正式文档版本。
- thread01a1163a-94aa-7440-9f86-baa23b27deaf：明确仅提交供RLD审阅，submit completed，REQ-0001正式v1/source3，phase仍planning，未执行研究。
- thread01a1163c-9682-7a70-82b2-f3df35273bf9：明确同REQ改PNG/path并提交，默认submit completed，正式v2，旧v1与原话保留；不误建另一REQ、不扩大执行权限。

默认明确confirm、root验收、reviewer可用/不可用/同族/五维/费用门等M4主场景仍待运行；不将上述UI成功等同整批完成。

## 新版协议、历史恢复与默认确认（12:30 UTC）

protocol.v1错把实验总数写成per-run required_counts，也把说明/别名放进top-level match；确认前没有运行或导入。控制器据实际runner契约指出问题，RLD登记protocol.v2 D-0017/说明D-0018，update_project绑定新协议，保留旧版；新init-plan.v3 D-0019仅允许root七run。match实际字段含simulation_only/model/data_version/data_seed/lr/batch_size/prediction_threshold/device/sanity=false，counts1200/400/30/1140，min_pairs3。M4-protocol-v2-before-confirm.json实际零experiment、T1 open未指派、phase awaiting_confirmation。

模型脚本覆写了D3/D4/D5历史v1，哈希门识别了差异。控制器从原native成功写入及登记前更正顺序重建，三文件全部先与已登记SHA256相等才恢复字节，损坏副本/收据M4-history-corruption与M4-history-restoration.json保留，数据库哈希未改；RLD三个verify_document均true。任意Python间接写入不在有界shell hook的沙箱保证内，不能宣称全部覆写均被提前拦截。

普通自然语言确认新版具体计划（没有省略project/readonly-handoff技术提示）启动第5个真实UI线程01a11653-36d3-7351-8bf8-5e709b00ace3，observed gpt-6-luna/native read-only；confirm action completed、D-0021确认登记、phase confirmed。全部5次UI动作/线程/原话与REQ同版本关系见更新M4-native-ui-proof.json。默认草稿、澄清、v1提交、v2修订与确认重测已通过；用户仅授权root七run，functional_probe、confirm seeds和PNG继续待授权。

真实root线程01a11655-596d-7ac2-99c1-8773544dda06，经安装包公共MCP和冻结runner实际完成七个valid run/七reservation全settled。RLD审计、返工交付后T1 accepted，现行交付D-0031，accepted依据D-0029/D-0030/D-0031/EV-0001/EV-0002/E-0001..3。两基线synthetic mean80.25pp，只是预先声明的功能公式；CPU训练诊断与原始模型另保留。M4-root-progress-1237.json保存完整实际状态。后续方法/五维/独立确认方案正在拟定，评审/费用门/R04/R19与最终页面未完成。


16:16 UTC：真实独立确认E8(root Adam 100/101/102)+E9(H1同methods commit)六run成功，与已有14run总20实际node-seconds，全部原始CPU产物由控制器逐一核对。EV6确认positive仅来自预置功能accuracy，仍明确simulation_only；新numbers/protocol实际Sonnet复核通过，原五维search绑定保留。OB01–04实际公开账本重复/重开/未解决消失/资格门通过；唯一功能性测试OB以明确控制器test-only用户指令waive，不豁免任何真实评审findings。合法functional GO DEC7/D103前后的独立资格及页面564/564 false保存。review raw累计1.2316206，DB1.231619，差异为逐次六位取整，含RV9付费失败。

E04测试出现控制器错误断言：短暂写非法JSON后get_eligibility仍true（设计并未要求每次重读磁盘），finally恢复原文件。控制器错误提前说自动失效/receipt已写而实际断言FAIL、receipt不存在；立即更正，但原生公开retract_run已在更正到达前完成。D105旧report及withdraw历史保留，D107更正版本明确原指标真实有效、仅test-only显式撤回、没有新科学发现或自动检测成功。实际撤回后H1 eligible=false/reason CONFIRMATION_STALE，历史EV6/DEC7与project go仍保留，RS18实际1秒/全项目20秒不变。原文件和控制器备份SHA04270cc0ad4cf22faf23c916f282dcefdbb6459eaf59f196f9506028bd3478dc字节一致。只计公开撤回传播测试，不声称后来证实科学无效或磁盘自动失效。R04临时同族配置已用普通CLI生效D108/v4，实际拒绝/R14/R19仍待完成。


16:31 UTC：R04一次真实同族拒绝（16:17:51）、R14一次真实review_usd_alert=.01拒绝（16:20:24、attention与页面阈值历史保留）、R19一次真实Claude未登录拒绝（16:26:33）均零新增费用；原YAML bytes已恢复、新config pointer D117/v7。R19前正常退出、remove/add最新插件，再同thread Full Access/never resume；实际MCP PID2496070的CODEX_HOME/CLAUDE_CONFIG_DIR由控制器`/proc`只读确认，仅隔离空Claude目录，日常配置不改。最终独立页面609/609 stale=false、无live/openRS、20实际秒、DB费1.231619，历史go与撤回后CONFIRMATION_STALE准确区分。终态与源码缓存刷新、默认UI、实际复核/GO前原始run、撤回更正和三probe证据已保存。Codex正常/exit、自建pJ关闭，原M4/project/home已归档并删除；tar SHA c8574cfe0b08968ff29dd0a70e3a32f465c293023f4bd2b366d35035fcb10cee，native2700条SHA cbe4771be6d6702553650dab4495d7c5dcf87fb464299ca62605236dd3af8bda。Fable最终审查尚待M8等全部补测完成，不能据此宣称全项目完成。
