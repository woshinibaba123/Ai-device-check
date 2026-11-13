"""Recognize explicit dismiss actions without accepting business confirmations."""
import re

def debug_panel_open(nodes):
    if not any('WebView' in n['kind'] for n in nodes):return False
    labels={n['label'].strip().casefold() for n in nodes}
    tabs=len(labels.intersection({'log','system','network','element','storage'}))
    return tabs>=3 and ('hide' in labels or 'vconsole' in labels)

CLOSE_LABELS={'关闭','关闭弹窗','取消','稍后','稍后再说','以后再说','暂不','暂不更新','跳过','知道了','我知道了','close','dismiss','cancel','later','not now','maybe later','remind me later','skip','got it','understood','×','✕','✖','x','閉じる','キャンセル','後で','スキップ','닫기','취소','나중에','fermer','annuler','plus tard','cerrar','cancelar','más tarde','schließen','abbrechen','später','chiudi','annulla','đóng','hủy','稍後','關閉','暫不'}
SYSTEM_PACKAGES={'com.android.permissioncontroller','com.google.android.permissioncontroller','com.android.systemui','com.apple.springboard'}
CLOSE_IDS={'close','dismiss','cancel','ic_close','icon_close','btn_close','button_close','close_button','dialog_close','iv_close','iv_cancel','permission_deny_button','permission_deny_and_dont_ask_again_button'}

def discard_target(nodes):
    """Only abandon an unsaved form when exploration is already returning."""
    text=' '.join(n['label'] for n in nodes).casefold()
    if not re.search(r'unsaved|discard (?:the |your )?changes|changes (?:will|won.t|will not)|未保存|尚未保存|放弃.*(?:编辑|修改)|放棄.*(?:編輯|修改)',text):return None
    choices={'discard','discard changes','leave','leave without saving','放弃修改','放弃','不保存','離開','放棄修改','放棄'}
    matches=[n for n in nodes if n['clickable'] and n['label'].strip().casefold() in choices]
    return matches[0] if len(matches)==1 else None


def privacy_update_target(nodes):
    labels={re.sub(r'\s+',' ',n['label']).strip().casefold() for n in nodes}
    # App-specific privacy update. Require all markers; never treat a generic agreement as Close.
    if not labels.intersection({'warm reminder','温馨提示','溫馨提示'}):return None
    if not any('privacy policy' in label or '隐私' in label or '隱私' in label for label in labels):return None
    if not labels.intersection({'disagree and quit','不同意并退出','不同意並退出'}):return None
    return next((n for n in nodes if n['clickable'] and n['label'].strip().casefold() in {'agree with','同意','同意并继续','同意並繼續'}),None)


def modal_present(nodes):
    return debug_panel_open(nodes) or privacy_update_target(nodes) is not None or any('dialog' in n['kind'].lower() or 'alert' in n['kind'].lower() or n['id'].endswith('/alertTitle') for n in nodes)


def close_target(nodes):
    if debug_panel_open(nodes):
        hide=next((n for n in nodes if n['clickable'] and n['label'].strip().casefold()=='hide'),None)
        return hide,'关闭 H5 调试面板，避免读取日志或存储数据'
    tutorial=tutorial_target(nodes)
    if tutorial:return tutorial,"最上层新手引导"
    guide=guide_overlay_target(nodes)
    if guide:return guide,'新手引导浮层遮挡，先完成引导'
    privacy=privacy_update_target(nodes)
    if privacy:return privacy,'该 App 隐私更新确认'
    candidates=[]
    for n in nodes:
        if not n['clickable'] or n['editable']:continue
        label=re.sub(r'\s+',' ',n['label']).strip().casefold()
        resource=n['id'].rsplit('/',1)[-1].casefold()
        if resource in CLOSE_IDS:candidates.append((0,n,'关闭控件标识'))
        elif label in CLOSE_LABELS:candidates.append((1,n,'关闭或跳过文字'))
    return min(candidates,key=lambda item:item[0])[1:] if candidates else (None,'')


def has_popup(nodes):
    return debug_panel_open(nodes) or modal_present(nodes) or close_target(nodes)[0] is not None


# 系统权限弹窗默认允许；只有测试用例明确要求拒绝权限时才点拒绝。
PERMISSION_PACKAGES={'com.android.permissioncontroller','com.google.android.permissioncontroller',
                     'com.lbe.security.miui','com.miui.securitycenter','com.apple.springboard'}
ALLOW_LABELS=('allow','ok','允许','allow all the time','始终允许','allow while using the app','while using the app',
              '仅在使用中允许','使用应用时允许','使用时允许','only this time','allow only this time','本次允许','仅本次允许')
DENY_LABELS=('deny',"don't allow",'refuse','不允许','拒绝','禁止')
PERMISSION_TEXT=('权限','permission','would like to access','获取您的位置','位置信息','定位','相机','相册','麦克风',
                 '通讯录','存储空间','camera','location','microphone','contacts')


def permission_target(nodes,deny=False):
    if not nodes:return None,''
    system=any(n.get('package') in PERMISSION_PACKAGES for n in nodes)
    text=' '.join(re.sub(r'\s+',' ',n.get('label','')).strip().casefold() for n in nodes)
    if not system and not any(marker in text for marker in PERMISSION_TEXT):return None,''
    wanted=DENY_LABELS if deny else ALLOW_LABELS
    def rank(n):
        label=re.sub(r'\s+',' ',n.get('label','')).strip().casefold()
        return wanted.index(label) if label in wanted else len(wanted)
    candidates=sorted((n for n in nodes if n.get('clickable') and rank(n)<len(wanted)),key=rank)
    if not candidates:return None,''
    node=candidates[0]
    return node,('系统权限弹窗默认'+('拒绝' if deny else '允许')+'：'+node['label'])


# Source-defined coachmark text; a generic Next button is never sufficient.
TUTORIAL_LABELS = frozenset({
    '[reparación] se ha movido a la página principal',
    '[riparazione] spostato in homepage',
    '[sửa chữa] đã chuyển đến trang chủ',
    '[広告]をクリックすると広告ページに移動します',
    '[店舗]をクリックすると、マイ店舗ページに入ります',
    'acceda aquí para ver las tiendas que sigue',
    'clicca per accedere alla pagina della chiamata',
    'clicca per tornare alla pagina del negozio',
    'clicca qui per visualizzare le informazioni',
    'clicca su [negozio] per andare alla pagina del mio negozio',
    'clicca su [pubblicità] per andare alla pagina pubblicità',
    'click [advertisement] to enter the advertisement page',
    'click [advertising] to enter the advertising page',
    'click [stores] to enter the my stores page',
    'click here to enter the robot top page',
    'click here to go to the call page',
    'click here to go to the robot top page',
    'click here to view the information',
    'click here to view the stores you are interested in',
    'click messages to see all your notifications',
    'click on messages to see all your notifications',
    'click on the message to see all your notifications',
    'click on this icon to view store information',
    'click to enter the call page',
    'click to enter the store page',
    'click to return to the store page',
    "cliquez ici pour accéder à la page d'accueil du robot",
    "cliquez ici pour accéder à la page d'appel",
    'cliquez ici pour accéder à la page du dessus du robot',
    "cliquez ici pour aller à la page d'accueil des robots",
    'cliquez ici pour obtenir des informations',
    'cliquez ici pour voir les informations',
    'cliquez ici pour voir les magasins qui vous intéressent',
    "cliquez pour accéder à la page de l'atelier",
    'cliquez pour revenir à la page du magasin',
    "cliquez sur [annonce] pour accéder à la page d'annonce",
    'cliquez sur [publicité] pour accéder à la page de publicité',
    'cliquez sur [store] pour accéder à la page mes magasins',
    'cliquez sur cette icône pour afficher les informations sur le magasin',
    'cliquez sur le message pour voir toutes vos notifications',
    'cliquez sur messages pour voir toutes vos notifications',
    "dai un'occhiata ai locali che segui per entrare",
    'die seite [meine seite] enthält viele neue inhalte. klicken sie jetzt, um sie anzusehen.',
    'fai clic su questa icona per visualizzare le informazioni sul negozio',
    'followed stores can be viewed in [mine] → [mine concerns].',
    'interessante geschäfte können unter [meine seite]→[meine interessen] eingesehen werden.',
    'kiểm tra các cửa hàng bạn đang theo dõi để vào',
    'klicken sie auf [geschäfte], um die seite „meine geschäfte“ zu öffnen.',
    'klicken sie auf [werbung], um die werbeseite zu öffnen.',
    'klicken sie auf die nachricht, um alle ihre benachrichtigungen anzusehen.',
    'klicken sie auf dieses symbol, um die geschäftsinformationen anzusehen.',
    'klicken sie auf nachrichten, um alle ihre benachrichtigungen anzusehen.',
    'klicken sie hier, um die geschäfte anzusehen, die sie interessieren.',
    'klicken sie hier, um die informationen anzusehen',
    'klicken sie hier, um zur anrufseite zu gelangen.',
    'klicken sie hier, um zur robot-oben-seite zu gelangen.',
    'klicken sie, um die geschäftsübernahmeseite zu öffnen.',
    'klicken sie, um zur geschäftsseite zurückzukehren.',
    'la página [mi cuenta] tiene contenido nuevo, ¡échale un vistazo!',
    'la reparación se ha movido a la página principal',
    'la reparación se ha movido a la página principal~',
    'la richiesta di riparazione è stata spostata nella pagina iniziale',
    'la richiesta di riparazione è stata spostata nella pagina iniziale ~',
    'las tiendas seguidas se pueden ver en [mi cuenta] → [mis seguidos]',
    "le rapport de réparation a été déplacé sur la page d'accueil",
    'les magasins suivis peuvent être consultés dans [le mien] → [mon attention].',
    'mục báo sửa chữa đã chuyển đến trang chủ',
    'mục báo sửa chữa đã chuyển đến trang chủ ~',
    'nella pagina [il mio profilo] sono disponibili nuovi contenuti. tocca per visualizzarli.',
    'nhấn vào tin nhắn để xem tất cả thông báo tin nhắn của bạn',
    'nhấn vào đây để mở trang ghim robot',
    'nhấn để mở trang nhận quyền quản lý cửa hàng',
    'nhấp vào [cửa hàng] để truy cập trang cửa hàng của tôi',
    'nhấp vào [quảng cáo] để chuyển đến trang quảng cáo',
    'nhấp vào biểu tượng này để xem thông tin cửa hàng',
    'nhấp vào đây để xem thông tin',
    'nhấp để quay lại trang cửa hàng',
    'nhấp để vào trang cuộc gọi',
    'pulse [publicidad] para entrar en la página de publicidad',
    'pulse [tienda] para entrar en mis tiendas',
    'pulse aquí para entrar en la página de fijar robots',
    'pulse aquí para ver información',
    'pulse este icono para ver la información de la tienda',
    'pulse mensajes para ver todas sus notificaciones',
    'pulse para entrar en la página de captura de tiendas',
    'pulse para entrar en la página de llamadas',
    'pulse para volver a la página de tiendas',
    'repair est passé à la première page',
    'repair has moved to the front page',
    'repair report has been moved to the home page',
    'repair report has moved to the home page',
    'reparatur wurde auf die startseite verschoben',
    'reparatur wurde auf die startseite verschoben ~',
    'tocca messaggi per visualizzare tutte le notifiche dei tuoi messaggi',
    'tocca per aprire la pagina dei robot fissati in alto',
    'tocca per aprire la pagina di acquisizione dei negozi',
    'trang [của tôi] có thêm nhiều nội dung mới. hãy nhấn để xem.',
    'visualizza i negozi seguiti in [il mio profilo] → [negozi seguiti]',
    'xem các cửa hàng đã theo dõi tại [của tôi] → [cửa hàng tôi theo dõi]',
    '【mine】there are many new contents on the page. click to view them now.',
    '【mine】ページ内に新しいコンテンツが多数あります。クリックして今すぐご覧ください。',
    '【mon】il y a beaucoup de nouveaux contenus sur la page. cliquez pour les voir maintenant.',
    '【報修】搬到首頁啦',
    '【我的】頁面新增多項內容，趕快點擊查看',
    '【我的】页面新增多项内容，赶快点击查看',
    '【报修】搬到首页啦',
    '【나의】페이지에 새로운 콘텐츠가 많이 있습니다. 지금 클릭하여 보세요.',
    'お電話のページはこちら',
    'このアイコンをクリックするとショップ情報が表示されます',
    'インフォメーションはこちら',
    'クリックするとショップページに戻ります',
    'クリックするとショップページに移動します',
    'コールページはこちら',
    'メッセージ]をクリックすると、すべてのお知らせが表示されます',
    'メッセージをクリックすると、すべてのお知らせが表示されます',
    'ロボットのトップページはこちら',
    'ロボットトップページはこちら',
    '修理がトップページに移動しました',
    '修理レポートはトップページに移動しました',
    '关注的门店可在【我的】→【我的关注】中查看',
    '報修搬到首頁啦',
    '報修搬到首頁啦～',
    '対応店舗は[設定]→[私の注意]で確認できます。',
    '広告]をクリックすると広告ページに入ります',
    '情報を見るにはここをクリック',
    '报修搬到首页啦',
    '报修搬到首页啦～',
    '查看关注的门店由此进入',
    '查看關注的門店由此進入',
    '点击【广告宣传】，进入广告宣传页面',
    '点击【门店】，进入我的门店页面',
    '点击此图标可查看门店信息',
    '点击此处，可查看资讯哦',
    '点击此处，进入机器人置顶页面',
    '点击消息，可查看您的所有消息通知',
    '点击进入呼叫页面',
    '点击进入抢门店页面',
    '点击，可返回门店页面',
    '興味のある店舗を見るにはここをクリックしてください',
    '關注的門店可在【我的】→【我的關注】中查看',
    '點擊【廣告宣傳】，進入廣告宣傳頁面',
    '點擊【門店】，進入我的門店頁面',
    '點擊此圖標可查看門店信息',
    '點擊此處，可查看資訊哦',
    '點擊此處，進入機器人置頂頁面',
    '點擊消息，可查看您的所有消息通知',
    '點擊進入呼叫頁面',
    '點擊進入搶門店頁面',
    '點擊，可返回門店頁面',
    '관심있는 매장을 보려면 여기를 클릭하세요',
    '광고]를 클릭하여 광고 페이지로 들어갑니다',
    '광고]를 클릭하여 광고 페이지로 이동',
    '광고]를 클릭하여 광고 페이지로 이동합니다',
    '로봇 메인 페이지로 이동하려면 여기를 클릭하세요',
    '로봇 상단 페이지로 이동하려면 여기를 클릭하세요',
    '메시지를 클릭하면 모든 알림을 볼 수 있습니다',
    '메시지를 클릭하여 모든 알림을 확인합니다',
    '상점 정보를 보려면 이 아이콘을 클릭하세요',
    '수리 보고서가 홈 페이지로 이동되었습니다',
    '수리 보고서가 홈 페이지로 이동했습니다',
    '수리가 첫 페이지로 이동했습니다',
    '스토어]를 클릭하여 내 스토어 페이지로 들어갑니다',
    '정보를 보려면 여기를 클릭하세요',
    '정보를 보려면 여기를 클릭합니다',
    '클릭하여 상점 페이지로 이동',
    '클릭하여 스토어 페이지로 돌아가기',
    '클릭하여 통화 페이지로 이동',
    '통화 페이지로 이동하려면 여기를 클릭하세요',
    '팔로우한 매장은 [내 매장] → [내 관심]에서 확인할 수 있습니다.',
})

def tutorial_target(nodes):
    if not any(n["label"].strip().casefold() in TUTORIAL_LABELS for n in nodes):return None
    # 引导层同时出现「跳过」和「下一步」时优先跳过，最快脱离遮挡。
    skip=[n for n in nodes if n["clickable"] and n["label"].strip().casefold() in {'skip','跳过','スキップ'}]
    if skip:return skip[0]
    advance=[n for n in nodes if n["clickable"] and n["label"].strip().casefold() in {"next","i know","下一步","知道了","我知道了","got it"}]
    return advance[-1] if advance else None


# 引导浮层的典型按钮组合：跳过（或 skip）与下一步/知道了并存。
# 无论哪个页面出现，都视为遮挡引导，第一时间跳过。
GUIDE_SKIP={'skip','跳过','スキップ'}

def guide_pair_target(nodes):
    skippable=[n for n in nodes if n['clickable'] and not n['editable'] and n['label'].strip().casefold() in GUIDE_SKIP]
    if not skippable:return None
    if not any(n['clickable'] and n['label'].strip().casefold() in GUIDE_ADVANCE for n in nodes):return None
    return skippable[0]


def dismiss_target(nodes):
    """遮挡类浮层（系统权限、新手引导、跳过+下一步引导）的即时关闭目标。

    只覆盖无争议的遮挡场景，不包含业务确认弹窗（取消/确定等留给上层流程决策）。
    """
    popup,reason=permission_target(nodes)
    if popup is not None:return popup,reason
    tutorial=tutorial_target(nodes)
    if tutorial is not None:return tutorial,'新手引导遮挡，立即关闭'
    guide=guide_pair_target(nodes)
    if guide is not None:return guide,'引导浮层遮挡（跳过+下一步并存），立即跳过'
    return None,''


# Guide overlays without a whitelisted coachmark still show a pager pair
# (e.g. previous step / I know) while covering a modal; advance them first,
# otherwise taps on the covered dialog are swallowed by the overlay mask.
GUIDE_BACK={'previous step','prev step','上一步'}
GUIDE_ADVANCE={'next','i know','下一步','知道了','我知道了','got it'}

def guide_overlay_target(nodes):
    if not modal_present(nodes):return None
    back=any(n['clickable'] and n['label'].strip().casefold() in GUIDE_BACK for n in nodes)
    if not back:return None
    advance=[n for n in nodes if n['clickable'] and n['label'].strip().casefold() in GUIDE_ADVANCE]
    return advance[-1] if advance else None
