"""把 M2 端到端时长 + 斯坦福时间占比合成网站用的 occupations.json。
格式：{"meta":{...}, "occ":[[onet_code, title_en, zh_name, [aliases], [[task, hours, share_pct, type], ...]], ...]}
type: 0 digital, 1 trust, 2 physical。"Specialize in..." 这类不是具体任务的条目剔除后重新归一化占比。"""
import argparse
import json
import os

import load
from load import load_frame

ap = argparse.ArgumentParser(description="生成 web/occupations.json")
ap.add_argument("--shares", choices=["own", "stanford"], default="own",
                help="时间占比来源：own（默认）= O*NET 频率 × M2 时长（own_shares.py）；stanford = Hatgis-Kessell et al. 的 s(t,o)")
ap.add_argument("--ratings", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "Task Ratings.xlsx"),
                help="--shares own 时需要：O*NET 30.2 的 Task Ratings.xlsx")
args = ap.parse_args()

df = load_frame(xlsx_path=None if args.shares == "own" else load.XLSX)
if args.shares == "own":
    import pandas as pd
    from own_shares import expected_freq, own_shares
    ratings = pd.read_excel(args.ratings) if args.ratings.endswith("xlsx") else pd.read_csv(args.ratings, sep="\t")
    # own_shares 算出的 per_day 替换掉斯坦福的；下面会按职业重新归一化成占比
    df = own_shares(df.drop(columns=["share", "per_day"]), expected_freq(ratings))
ZH = {
 'Software Developers':('软件工程师',['程序员','码农','开发','后端','前端','software engineer','developer','sde','swe','programmer']),
 'Web Developers':('网页开发',['前端开发','web developer','webdev','web dev','网站开发']),
 'Computer Programmers':('程序员（编码）',['coder']),
 'Computer and Information Research Scientists':('计算机研究科学家',['ai 研究员','研究科学家','research scientist','ml researcher','机器学习','machine learning']),
 'Database Administrators':('数据库管理员',['dba']),
 'Information Security Analysts':('信息安全分析师',['网络安全','安全工程师','security analyst']),
 'Computer Systems Analysts':('计算机系统分析师',['系统分析']),
 'Computer User Support Specialists':('IT 支持',['it support','技术支持','help desk']),
 'Network and Computer Systems Administrators':('网络管理员',['运维','sysadmin','系统管理员']),
 'Information Technology Project Managers':('IT 项目经理',['项目经理','project manager','pm']),
 'Video Game Designers':('游戏设计师',['游戏策划','game designer']),
 'Accountants and Auditors':('会计师',['会计','审计','cpa','财务','accountant','auditor']),
 'Bookkeeping, Accounting, and Auditing Clerks':('记账员',['记账','出纳','bookkeeper']),
 'Tax Preparers':('报税员',['报税','tax preparer']),
 'Financial Managers':('财务经理',['财务总监','cfo']),
 'Financial Quantitative Analysts':('量化分析师',['量化','quant','金融工程']),
 'Personal Financial Advisors':('理财顾问',['理财','financial advisor']),
 'Credit Analysts':('信用分析师',['信贷分析']),
 'Budget Analysts':('预算分析师',[]),
 'Loan Officers':('信贷员',['贷款专员','loan officer']),
 'Insurance Underwriters':('保险核保',['核保','underwriter']),
 'Insurance Sales Agents':('保险销售',['卖保险','保险代理']),
 'Claims Adjusters, Examiners, and Investigators':('理赔员',['理赔']),
 'Actuaries':('精算师',['精算','actuary']),
 'Securities, Commodities, and Financial Services Sales Agents':('证券经纪',['券商','经纪人','broker']),
 'Market Research Analysts and Marketing Specialists':('市场研究分析师',['市场调研','市场营销','marketing','market research']),
 'Marketing Managers':('市场经理',['营销经理','marketing manager']),
 'Advertising and Promotions Managers':('广告经理',['广告']),
 'Public Relations Specialists':('公关',['pr','public relations']),
 'Sales Managers':('销售经理',[]),
 'Business Intelligence Analysts':('数据分析师',['数据分析','bi','data analyst','analyst','商业分析']),
 'Statisticians':('统计学家',['统计','数据科学家','data scientist','statistician']),
 'Biostatisticians':('生物统计师',['生物统计']),
 'Operations Research Analysts':('运筹分析师',['运筹','operations research']),
 'Management Analysts':('管理咨询顾问',['咨询','顾问','consultant','管理咨询']),
 'General and Operations Managers':('运营经理',['总经理','运营','operations manager']),
 'Human Resources Specialists':('HR 专员',['人力资源','hr','招聘','recruiter']),
 'Human Resources Managers':('HR 经理',['人事经理']),
 'Logisticians':('物流规划师',['物流','供应链','supply chain']),
 'Purchasing Agents, Except Wholesale, Retail, and Farm Products':('采购专员',['采购','buyer']),
 'Mathematicians':('数学家',['数学','数学研究','mathematician','math']),
 'Economists':('经济学家',['经济','economist']),
 'Bioinformatics Scientists':('生物信息科学家',['生物信息','生信','bioinformatics','计算生物','computational biology']),
 'Bioinformatics Technicians':('生物信息技术员',['生信分析']),
 'Biologists':('生物学家',['生物','biologist']),
 'Molecular and Cellular Biologists':('分子生物学家',['分子生物','细胞生物']),
 'Chemists':('化学家',['化学','chemist']),
 'Physicists':('物理学家',['物理','physicist']),
 'Epidemiologists':('流行病学家',['流行病']),
 'Historians':('历史学家',['历史']),
 'Sociologists':('社会学家',['社会学']),
 'Psychology Teachers, Postsecondary':('心理学教授',[]),
 'Clinical and Counseling Psychologists':('心理咨询师',['心理医生','心理咨询','psychologist','counselor']),
 'Lawyers':('律师',['lawyer','attorney','法务']),
 'Paralegals and Legal Assistants':('律师助理',['paralegal','法务助理','legal assistant']),
 'Judges, Magistrate Judges, and Magistrates':('法官',['judge']),
 'Interpreters and Translators':('翻译',['口译','笔译','translator','interpreter']),
 'Writers and Authors':('作家',['作者','写作','writer','author','文案']),
 'Technical Writers':('技术文档工程师',['技术写作','technical writer']),
 'Editors':('编辑',['editor']),
 'Proofreaders and Copy Markers':('校对',['proofreader']),
 'News Analysts, Reporters, and Journalists':('记者',['新闻','journalist','reporter']),
 'Graphic Designers':('平面设计师',['设计师','美工','designer','graphic designer','视觉设计']),
 'Special Effects Artists and Animators':('动画师',['特效','animator']),
 'Film and Video Editors':('视频剪辑师',['剪辑','video editor']),
 'Photographers':('摄影师',['摄影','photographer']),
 'Interior Designers':('室内设计师',['室内设计']),
 'Fashion Designers':('服装设计师',['服装设计']),
 'Architects, Except Landscape and Naval':('建筑师',['建筑设计','architect']),
 'Civil Engineers':('土木工程师',['土木','civil engineer']),
 'Mechanical Engineers':('机械工程师',['机械','mechanical engineer']),
 'Electrical Engineers':('电气工程师',['电气','electrical engineer']),
 'Registered Nurses':('注册护士',['护士','护理','nurse','rn']),
 'Family Medicine Physicians':('家庭医生',['医生','全科医生','doctor','gp']),
 'Radiologists':('放射科医生',['放射科','radiologist']),
 'Pharmacists':('药剂师',['药师','pharmacist']),
 'Dentists, General':('牙医',['dentist']),
 'Dental Hygienists':('牙科卫生士',['洁牙']),
 'Physical Therapists':('物理治疗师',['理疗','physiotherapist']),
 'Veterinarians':('兽医',['vet']),
 'Dietitians and Nutritionists':('营养师',['dietitian']),
 'Medical Transcriptionists':('医学转录员',[]),
 'Medical Secretaries and Administrative Assistants':('医疗秘书',[]),
 'Elementary School Teachers, Except Special Education':('小学老师',['小学教师','老师','teacher']),
 'Secondary School Teachers, Except Special and Career/Technical Education':('中学老师',['中学教师','高中老师']),
 'Kindergarten Teachers, Except Special Education':('幼儿园老师',['幼师']),
 'Librarians and Media Collections Specialists':('图书馆员',['图书管理员','librarian']),
 'Executive Secretaries and Executive Administrative Assistants':('行政助理',['秘书','助理','executive assistant']),
 'Receptionists and Information Clerks':('前台',['接待','receptionist']),
 'Customer Service Representatives':('客服代表',['客服','customer service','call center','呼叫中心','售后']),
 'Telemarketers':('电话销售',['电销','telemarketer']),
 'Data Entry Keyers':('数据录入员',['录入','data entry']),
 'Real Estate Sales Agents':('房产中介',['地产经纪','realtor']),
 'Retail Salespersons':('零售店员',['店员','导购','销售员']),
 'Cashiers':('收银员',['收银','cashier']),
 'Waiters and Waitresses':('服务员',['waiter']),
 'Bartenders':('调酒师',['bartender']),
 'Chefs and Head Cooks':('厨师长',['厨师','chef']),
 'Cooks, Restaurant':('餐厅厨师',['cook']),
 'Barbers':('理发师',['barber']),
 'Hairdressers, Hairstylists, and Cosmetologists':('发型师',['美发','hairdresser']),
 'Electricians':('电工',['electrician']),
 'Plumbers, Pipefitters, and Steamfitters':('水管工',['plumber']),
 'Carpenters':('木工',['carpenter']),
 'Construction Laborers':('建筑工人',['工地']),
 'Heavy and Tractor-Trailer Truck Drivers':('卡车司机',['司机','货车','truck driver']),
 'Shuttle Drivers and Chauffeurs':('专车司机',['网约车','taxi','uber']),
 'Couriers and Messengers':('快递员',['快递','外卖','courier']),
 'Security Guards':('保安',['security guard']),
 "Police and Sheriff's Patrol Officers":('警察',['police']),
 'Firefighters':('消防员',['firefighter']),
 'Airline Pilots, Copilots, and Flight Engineers':('飞行员',['机长','pilot']),
 'Janitors and Cleaners, Except Maids and Housekeeping Cleaners':('清洁工',['保洁','janitor']),
 'Childcare Workers':('育儿员',['保姆','托育']),
 'Travel Agents':('旅行社顾问',['旅行社']),
 'Meeting, Convention, and Event Planners':('活动策划',['会展','event planner']),
 'Farmers, Ranchers, and Other Agricultural Managers':('农场主',['农民','farmer']),
}
# 其余职业的中文名（没有别名）：web/zh_names.tsv，每行「英文名<TAB>中文名」
_tsv = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zh_names.tsv")
ZH_EXTRA = dict(line.rstrip("\n").split("\t", 1) for line in open(_tsv, encoding="utf-8") if "\t" in line)
missing=[k for k in ZH if k not in set(df.occupation)]
print('ZH titles not in data:', missing)
TYPE={'digital':0,'trust':1,'physical':2}
d=df[~df.task.str.match(r'^Specializ')].copy()
d['share']=d['per_day']/d.groupby('onet_code')['per_day'].transform('sum')
out=[]
for code,g in d.groupby('onet_code'):
    title=g.occupation.iloc[0]; zh,al=ZH.get(title,(ZH_EXTRA.get(title,''),[]))
    tasks=[[t, round(float(h),2), round(float(s)*100,2), TYPE[ty]] for t,h,s,ty in zip(g.task,g.hours,g.share,g.task_type)]
    tasks.sort(key=lambda x:-x[2])
    out.append([code,title,zh,al,tasks])
meta={'source':'O*NET 30.2 tasks; time shares: '+('Hatgis-Kessell et al. 2026' if args.shares=='stanford' else 'O*NET 30.2 frequency x relevance x min(M2 hours, 7h)')+'; end-to-end hours: M2 (Qwen2.5-32B-Instruct-AWQ, prompt v3.1, median of 5 samples)','n_occ':len(out),'n_tasks':int(len(d))}
json.dump({'meta':meta,'occ':out},open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'occupations.json'),'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
print(meta, 'with zh:',sum(1 for o in out if o[2]))
