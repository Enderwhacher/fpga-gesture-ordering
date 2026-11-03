"""640x480 OpenCV UI; all food assets are loaded/resized once, not each frame."""
from pathlib import Path
import cv2
import numpy as np
from order_core import MENU

BG = (238, 245, 250)
INK = (44, 49, 45)
MUTED = (108, 116, 110)
GREEN = (78, 120, 24)
WHITE = (255, 255, 255)


def text(canvas, value, x, y, size=.5, color=INK, width=None):
    if width:
        while cv2.getTextSize(str(value), cv2.FONT_HERSHEY_SIMPLEX, size, 1)[0][0] > width:
            size *= .95
    cv2.putText(canvas, str(value), (x,y), cv2.FONT_HERSHEY_SIMPLEX,
                size, color, 1, cv2.LINE_AA)


class OrderUI:
    def __init__(self, asset_dir):
        self.photos = []
        for item in MENU:
            file = Path(asset_dir)/item['image']
            # imdecode also works on Windows paths containing non-ASCII characters.
            photo = cv2.imdecode(np.fromfile(str(file), dtype=np.uint8), cv2.IMREAD_COLOR) if file.is_file() else None
            if photo is None:
                photo=np.full((136,136,3),(220,231,223),np.uint8)
                cv2.circle(photo,(68,56),34,(237,244,238),-1)
                text(photo,item['name'],10,112,.5,GREEN,width=116)
            self.photos.append(cv2.resize(photo, (136,136), interpolation=cv2.INTER_AREA))

    def set_photo(self,index,photo):
        self.photos[index]=cv2.resize(photo,(136,136),interpolation=cv2.INTER_AREA)

    def render(self, state, gate=None, camera=None, metrics=None):
        gate = gate or dict(status='WAITING FOR AI', progress=0)
        metrics = metrics or {}
        page = state['page']
        a = np.full((480,640,3), BG, np.uint8)
        cv2.rectangle(a,(0,0),(639,58),INK,-1)
        text(a,'HAND ORDER / 02',16,27,.76,WHITE)
        text(a,'PYNQ-ZU  /  TOUCHLESS DEMO',16,47,.37,(160,205,189))
        text(a,metrics.get('backend_label','WAITING FOR AI'),486,23,.39,(120,220,190),width=140)
        text(a,'Simulated order',486,43,.36,WHITE)
        # Sidebar stays visible on all screens.
        cv2.rectangle(a,(482,67),(631,385),WHITE,-1)
        text(a,'CAMERA',491,84,.37,MUTED)
        if camera is not None:
            a[92:188,490:618] = cv2.resize(camera,(128,96))
        else:
            cv2.rectangle(a,(490,92),(618,187),(220,227,224),-1)
            text(a,'Waiting...',500,143,.43,MUTED)
        text(a,'YOUR CART',491,211,.43,GREEN)
        for i,item in enumerate(MENU):
            text(a,f"{item['name']}  x{state['cart'][i]}",491,235+i*22,.4)
        text(a,'CNY %.2f' % (state['total_fen']/100),491,312,.54,GREEN)
        text(a,'Display %.1f fps'%metrics.get('display_fps',0),491,338,.33,MUTED)
        text(a,'AI %.2f /s'%metrics.get('ai_hz',0),491,355,.33,MUTED)
        if metrics.get('detector_ms') is not None:
            text(a,'D %.0f / C %.0f ms'%(metrics['detector_ms'],metrics.get('classifier_ms',0)),491,372,.31,MUTED)
        if metrics.get('fpga_call_ms') is not None:
            text(a,'FPGA call %.2f ms'%metrics['fpga_call_ms'],491,385,.28,GREEN)
        title = dict(WELCOME='ORDER WITH A GESTURE',MENU='CHOOSE YOUR FOOD',
                     REVIEW='REVIEW YOUR ORDER',DONE='THANK YOU!',EXIT_CONFIRM='LEAVE THIS ORDER?')[page]
        text(a,title,16,85,.59,GREEN)
        if page in ('MENU','WELCOME'):
            for i,(item,photo) in enumerate(zip(MENU,self.photos)):
                x = 16+i*154
                chosen = page == 'MENU' and i == state['selected']
                cv2.rectangle(a,(x-2,100),(x+140,293),GREEN if chosen else WHITE,-1)
                a[104:240,x:x+136] = photo
                color = WHITE if chosen else INK
                text(a,item['name'],x+8,260,.49,color)
                text(a,'CNY %.2f'%(item['price_fen']/100),x+8,282,.49,color)
                if page == 'MENU' and state['cart'][i]:
                    cv2.rectangle(a,(x+91,108),(x+131,131),INK,-1)
                    text(a,'x%d'%state['cart'][i],x+98,125,.42,WHITE)
            text(a,'OPEN PALM TO START' if page=='WELCOME' else state['message'],16,324,.57,GREEN,width=450)
            text(a,'FIST: review cart / remove an item' if page=='MENU' else
                 'Burger 18 + Cola 6 + Fries 9 = CNY 33',16,349,.43,MUTED)
            text(a,'Keep your whole hand inside the camera view.',16,372,.39,MUTED)
        elif page in ('REVIEW','DONE'):
            cv2.rectangle(a,(16,102),(465,296),WHITE,-1)
            text(a,'ITEM',28,124,.42,MUTED)
            text(a,'QTY',265,124,.42,MUTED)
            text(a,'CNY',359,124,.42,MUTED)
            for i,item in enumerate(MENU):
                y = 158+i*36
                selected = page=='REVIEW' and state.get('review_selected')==i and state['cart'][i]>0
                if selected:
                    cv2.rectangle(a,(22,y-24),(457,y+8),GREEN,-1)
                color = WHITE if selected else (INK if state['cart'][i] else MUTED)
                text(a,item['name'],28,y,.56,color)
                text(a,state['cart'][i],280,y,.56,color)
                text(a,'%.2f'%(item['price_fen']*state['cart'][i]/100),357,y,.56,color)
            text(a,'TOTAL',28,277,.56,GREEN)
            text(a,'CNY %.2f'%(state['total_fen']/100),300,277,.56,GREEN)
            if page == 'DONE':
                text(a,'DEMO ORDER #%03d'%state['order_count'],16,326,.69,GREEN)
                text(a,'Recorded locally. Not paid or sent to a restaurant.',16,354,.38,MUTED)
            else:
                text(a,state['message'],16,321,.52,GREEN,width=448)
                if any(state['cart']):
                    text(a,'OPEN: next row     FIST: remove one',16,346,.44,MUTED)
                    text(a,'THUMB: confirm order     V: keep shopping',16,371,.43,MUTED)
                else:
                    text(a,'No items left. Checkout is unavailable.',16,346,.44,MUTED)
                    text(a,'V: return to the menu and choose food',16,371,.43,GREEN)
        else:
            text(a,'Discard the current cart?',28,151,.68)
            text(a,'THUMBS UP: yes, return home',28,212,.56,GREEN)
            text(a,'V: no, keep this order',28,253,.56)
            text(a,'Nothing has been purchased.',28,320,.45,MUTED)
        cv2.rectangle(a,(8,393),(631,473),INK,-1)
        status = gate['status']
        if status.startswith('HOLD '):
            gesture = status[5:].lower()
            action = {
                'WELCOME': {'open_palm':'START ORDER'},
                'MENU': {'open_palm':'NEXT FOOD','thumbs_up':'ADD ONE','fist':'REVIEW CART','victory':'EXIT'},
                'REVIEW': {'open_palm':'NEXT ROW','thumbs_up':'CONFIRM ORDER','fist':'REMOVE ONE','victory':'BACK TO MENU'},
                'DONE': {'open_palm':'NEW ORDER','victory':'HOME'},
                'EXIT_CONFIRM': {'thumbs_up':'DISCARD CART','victory':'KEEP CART'},
            }[page].get(gesture)
            if page=='REVIEW' and not any(state['cart']) and gesture!='victory':
                action=None
            status = 'HOLD TO '+action if action else 'NO ACTION - USE THE GESTURES BELOW'
        elif status=='REMOVE HAND':
            status='ACTION LOCKED - REMOVE HAND TO CONTINUE'
        elif status=='READY':
            status='READY - SHOW ONE GESTURE AND HOLD'
        text(a,status,17,413,.43,(150,232,204),width=600)
        cv2.rectangle(a,(17,421),(620,425),(80,83,80),-1)
        progress = max(0,min(1,gate.get('progress',0)))
        if progress:
            cv2.rectangle(a,(17,421),(17+int(603*progress),425),(120,212,158),-1)
        hints = {
            'WELCOME': 'OPEN: start  |  Hold, then remove your hand',
            'MENU': 'OPEN: next   THUMB: add   FIST: checkout   V: exit',
            'REVIEW': 'OPEN: row   FIST: -1   THUMB: confirm   V: back',
            'DONE': 'OPEN: new order   V: home',
            'EXIT_CONFIRM': 'THUMB: discard   V: cancel',
        }
        if page=='REVIEW' and not any(state['cart']):
            hints['REVIEW']='CART EMPTY   |   V: back to menu'
        text(a,hints[page],17,444,.4,WHITE,width=605)
        text(a,'After each action: remove hand until READY, then show the next gesture.',17,464,.35,(175,187,181),width=605)
        return a
