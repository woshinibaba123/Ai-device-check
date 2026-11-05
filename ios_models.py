"""Source-backed iOS references; only bind to actual Simulator device types."""
import copy

DUO = {
    'id':'iphone-duo', 'brand':'苹果', 'name':'iPhone Duo', 'platform':'iOS',
    'system':'iOS 27', 'source':'https://www.apple.com/iphone-duo/specs/',
    'setup_source':'https://developer.apple.com/iphone-duo/',
    'checked':'2026-10-22',
    'displays':[
        {'name':'外屏','inches':5.4,'width':1398,'height':2034},
        {'name':'内屏','inches':7.6,'width':1878,'height':2670}],
    'coverage':'仅在官方模拟器当前屏幕状态执行点击、多语言及截图；自动展开、合上和半折叠切换尚未接入，页面截图需人工复核。'
}

def references(device_types, devices):
    profile=copy.deepcopy(DUO)
    ids={d['identifier'] for d in device_types if d.get('name')=='iPhone Duo' and d.get('identifier')}
    matches=[d for d in devices if d.get('platform')=='iOS' and d.get('device_type') in ids]
    profile['devices']=[{'id':d['id'],'name':d['name']} for d in matches]
    profile['available']=bool(matches)
    profile['reason']=('已发现官方机型模拟器；折叠状态需手动设置，驱动兼容性尚需首次运行验证。' if matches else
        '未发现官方 iPhone Duo 模拟器。请安装 Apple Duo 开发页面提供的 Xcode（当前为 27.1），安装配套 iOS runtime，并创建 iPhone Duo 模拟器，再刷新环境。')
    return [profile]

def resolve(selection, profiles):
    profile=next((p for p in profiles if p['id']==selection.get('id')),None)
    if not profile: raise ValueError('未知 iOS 参考机型')
    if not profile['available']: raise ValueError(profile['name']+'：'+profile['reason'])
    device=next((d for d in profile['devices'] if d['id']==selection.get('device')),None)
    if not device: raise ValueError('请选择该机型当前可用的官方模拟器')
    return profile, device
