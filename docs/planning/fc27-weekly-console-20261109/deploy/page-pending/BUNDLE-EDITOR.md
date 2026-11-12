# 四个固定组合的原编辑器升级

用户澄清单独交付、不挂主站的是RTTK推广素材；固定组合继续按原清单处理。实际只读复核center/public27，草稿原有53模型、三页均使用缺省商品列表、四包仍为legacy goods key，未导入对应模型。

真实编辑器检索model44839987后显示“复用原卡”：`matchingKey`按三平台goods回到旧key，`modelImports`又只检查显式现代product_keys，故可信模型资料被过滤。原`syncLayoutSelection`还会将缺省页面选择显式化。后台原center/save已有所需能力，无需新API、认证、CLI或发布器。

最小改动仅`analytics/products.js`：三平台verified、goods全部相同且旧包身份唯一时，将原布局位置升级为现代model key；缺省页面字段原样保留，显式列表按同平台原位重命名并保留role及平台子集；pending imports按对应页面实际布局收集。非升级场景保持原选卡逻辑，缺平台/身份歧义不自动替换旧包。

新真实production-server/Playwright回归先复现失败，再验证四包一次save4imports、53旧模型逐项保留、保存后57模型、整份draft除bundles和4新模型外深相等、published不变；未保存无写、重复选择不重复、缺失/歧义平台不替换、重复旧身份不升级、显式仅PS不扩Xbox/PC。原model-media/page-flow/draft-compat/preview-entry回归和语法检查通过。新测试沿现有pr_fast glob纳入，不改CI。

生产候选应仅部署products.js。现场已核它每请求动态读取且Cache-Control:no-store；products.html无版本参数，110项runtime static manifest不包含products.*，因此不改HTML/manifest、不重启业务服务或价格producer。沿现役UI-only publisher保留原锁、CAS、备份与范围回退，真实部署及四包业务保存/发布另记录，不以回归通过代替上线。
