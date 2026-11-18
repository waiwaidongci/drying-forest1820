import hashlib,json
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split,KFold,cross_val_score,GroupShuffleSplit,GroupKFold
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_absolute_error,mean_squared_error
from .domain_validation import validate_parameters
FEATURES=['moisture','thickness','temperature','airflow']
SUBSETS=[['moisture','temperature'],['moisture','thickness','temperature'],FEATURES]
def calculate(records,parameters):
    p=validate_parameters(parameters)
    if len(records)<40:raise ValueError('至少40条独立工艺样本，才能拆分训练与留出验证')
    groups=np.array([int(r.get('group',i)) for i,r in enumerate(records)])
    X=np.array([[r['values'][f] for f in FEATURES] for r in records],float);y=np.array([r['values']['minutes'] for r in records],float)
    indices=np.arange(len(records))
    unique_groups=np.unique(groups);group_aware=len(unique_groups)>1
    if group_aware:
        # 母料组隔离：同一母料（含间接关联）的试件要么全在训练、要么全在留出。
        if len(unique_groups)<4:raise ValueError('母料组数不足4组，无法按组隔离拆分训练与留出，请补充无亲缘来源')
        splitter=GroupShuffleSplit(n_splits=1,test_size=.25,random_state=42)
        train,test=next(splitter.split(X,y,groups))
        if len(train)<20 or len(test)<10:raise ValueError('按母料组拆分后训练或留出样本不足，请补充样本后再执行')
    else:
        train,test=train_test_split(indices,test_size=.25,random_state=42)
    # 训练内特征子集选择同样按组隔离：交叉验证的每折都不跨母料组。
    if group_aware:
        n_splits=min(3,len(np.unique(groups[train])))
        if n_splits<2:raise ValueError('训练侧母料组数不足，无法完成组内交叉验证')
        cv=GroupKFold(n_splits)
        cv_groups=groups[train]
    else:
        cv=KFold(3,shuffle=True,random_state=42);cv_groups=None
    candidates=[]
    for subset in SUBSETS:
        cols=[FEATURES.index(f) for f in subset]
        model=RandomForestRegressor(n_estimators=p['trees'],max_depth=p['depth'],random_state=42,n_jobs=1)
        errors=-cross_val_score(model,X[train][:,cols],y[train],cv=cv,groups=cv_groups,scoring='neg_mean_absolute_error',n_jobs=1)
        candidates.append({'features':subset,'cv_mae':float(errors.mean()),'fold_mae':errors.tolist()})
    best=min(candidates,key=lambda c:c['cv_mae']);cols=[FEATURES.index(f) for f in best['features']]
    model=RandomForestRegressor(n_estimators=p['trees'],max_depth=p['depth'],random_state=42,n_jobs=1).fit(X[train][:,cols],y[train]);pred=model.predict(X[test][:,cols])
    importance=permutation_importance(model,X[test][:,cols],y[test],n_repeats=5,random_state=42,scoring='neg_mean_absolute_error',n_jobs=1)
    features=[{'feature':f,'mae_increase':float(v),'std':float(s)} for f,v,s in zip(best['features'],importance.importances_mean,importance.importances_std)]
    rows=[{'reference':records[i]['reference'],'group':int(groups[i]),'actual_minutes':float(y[i]),'predicted_minutes':float(pred[j]),'error_minutes':float(pred[j]-y[i])} for j,i in enumerate(test)]
    holdout_groups=sorted(set(int(g) for g in groups[test]))
    summary=[{'label':'留出 MAE / min','value':float(mean_absolute_error(y[test],pred))},{'label':'留出 RMSE / min','value':float(np.sqrt(mean_squared_error(y[test],pred)))},{'label':'训练样本','value':len(train)},{'label':'留出样本','value':len(test)},{'label':'拆分口径','value':('母料组隔离 · '+str(len(unique_groups))+'组') if group_aware else '行级随机拆分（无已认母料关系）'}]
    if group_aware:summary.append({'label':'留出母料组','value':len(holdout_groups)})
    return {'summary':summary, 'candidates':candidates,'selected_features':best['features'],'importance':features,'train_indices':train.tolist(),'holdout_indices':test.tolist(),'group_aware':group_aware,'holdout_groups':holdout_groups,'training_checksum':hashlib.sha256(X[train].tobytes()+y[train].tobytes()).hexdigest(),'rows':rows,'columns':['reference','group','actual_minutes','predicted_minutes','error_minutes'],'chart':[{'label':x['feature'],'value':x['mae_increase']} for x in features],'explanation':('按母料连通分量组隔离拆分：同母料（含间接关联）试件不会同时进入训练与留出；特征选择的交叉验证同样按组。' if group_aware else '固定seed先拆25%留出；仅训练集3折MAE选择特征子集。')+'图为留出置换MAE增量，可为负值，不是因果效应或概率区间。','checksum':hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest(),'seed':42}
