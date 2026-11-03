"""Hardware-independent demo ordering logic. Money is stored in integer fen."""
from copy import deepcopy
import math

MENU = [
    dict(id='burger', name='BURGER', price_fen=1800, image='burger.png'),
    dict(id='cola', name='COLA', price_fen=600, image='cola.png'),
    dict(id='fries', name='FRIES', price_fen=900, image='fries.png'),
]
LABELS = ('open_palm', 'fist', 'victory', 'thumbs_up')


class GestureGate:
    """Only NEW, fresh camera results count. Explicit no-hand releases the latch.

    An uncertain classification is NOT a release. After firing, even a different
    gesture stays blocked until two no-hand observations span release_seconds.
    This trades interaction speed for predictable demonstration behavior.
    """
    def __init__(self, required=2, hold_seconds=.35, release_seconds=.35,
                 min_score=.60, max_age=1.5, max_gap=2.0):
        self.required, self.hold_seconds = required, hold_seconds
        self.release_seconds, self.min_score = release_seconds, min_score
        self.max_age, self.max_gap = max_age, max_gap
        self.armed = True
        self.last_source = None
        self.blocked_before = float('-inf')
        self.candidate = None
        self.count = 0
        self.since = None
        self.release_since = None
        self.release_count = 0
        self.status = 'READY'
        self.progress = 0.0

    def reset_candidate(self):
        self.candidate, self.since, self.count = None, None, 0
        self.progress = 0.0

    def invalidate(self, status='BOARD OFFLINE - REMOVE HAND', reset_source=False):
        """A transport fault is never interpreted as a physical hand release."""
        self.armed = False
        self.reset_candidate()
        self.release_since, self.release_count = None, 0
        self.status = status
        if reset_source:
            self.last_source = None
            self.blocked_before = float('-inf')

    def update(self, label, score, detected, source_time, now):
        if self.last_source is not None and source_time <= self.last_source:
            return None
        gap = self.last_source is not None and source_time-self.last_source > self.max_gap
        self.last_source = source_time
        if source_time <= self.blocked_before:
            self.status = 'REMOVE HAND'
            return None
        if now-source_time > self.max_age or source_time > now or gap:
            self.armed = False
            self.reset_candidate()
            self.release_since, self.release_count = None, 0
            self.status = 'STALE - REMOVE HAND'
            return None
        if not detected:
            self.reset_candidate()
            if self.release_since is None:
                self.release_since = source_time
            self.release_count += 1
            if self.release_count >= 2 and source_time-self.release_since >= self.release_seconds:
                self.armed = True
            self.status = 'READY' if self.armed else 'REMOVE HAND'
            return None
        self.release_since, self.release_count = None, 0
        if not self.armed:
            self.status = 'REMOVE HAND'
            return None
        if label not in LABELS or not math.isfinite(score) or score < self.min_score:
            self.reset_candidate()
            self.status = 'UNCERTAIN - HOLD CLEARLY'
            return None
        if self.candidate != label:
            self.candidate, self.since, self.count = label, source_time, 1
        else:
            self.count += 1
        elapsed = source_time-self.since
        self.progress = min(1.0, self.count/self.required, elapsed/max(self.hold_seconds, .001))
        self.status = 'HOLD ' + label.upper()
        if self.count >= self.required and elapsed >= self.hold_seconds:
            self.armed = False
            self.blocked_before = now
            self.reset_candidate()
            self.status = 'REMOVE HAND'
            return label
        return None

    def snapshot(self):
        return dict(status=self.status, progress=self.progress, armed=self.armed,
                    candidate=self.candidate, count=self.count)


class OrderController:
    def __init__(self, menu=None, save_order=None):
        self.menu = deepcopy(MENU if menu is None else menu)
        self.page = 'WELCOME'
        self.selected = 0
        self.review_selected = 0
        self.cart = [0]*len(self.menu)
        self.orders = []
        self.events = []
        self.message = 'OPEN PALM TO START'
        self.resume_page = 'MENU'
        self.save_order = save_order

    def select_cart_item(self, advance=False):
        """Skip zero-quantity rows. Keep selection when it still has items."""
        available = [i for i, qty in enumerate(self.cart) if qty > 0]
        if not available:
            self.review_selected = None
        elif self.review_selected not in available:
            self.review_selected = available[0]
        elif advance:
            self.review_selected = available[(available.index(self.review_selected)+1) % len(available)]

    @property
    def total_fen(self):
        return sum(item['price_fen']*qty for item, qty in zip(self.menu, self.cart))

    def handle(self, gesture, now):
        before = self.page
        action = 'ignored'
        if self.page in ('WELCOME', 'DONE'):
            if gesture == 'open_palm':
                self.cart = [0]*len(self.menu)
                self.selected = 0
                self.review_selected = None
                self.page, action = 'MENU', 'start'
                self.message = 'CHOOSE YOUR FOOD'
            elif gesture == 'victory' and self.page == 'DONE':
                self.page, action = 'WELCOME', 'return_home'
                self.cart = [0]*len(self.menu)
                self.message = 'OPEN PALM TO START'
        elif self.page == 'MENU':
            if gesture == 'open_palm':
                self.selected = (self.selected+1) % len(self.menu)
                action, self.message = 'next', 'ITEM SELECTED'
            elif gesture == 'thumbs_up':
                if self.cart[self.selected] < 9:
                    self.cart[self.selected] += 1
                    action, self.message = 'add', 'ADDED '+self.menu[self.selected]['name']
                else:
                    self.message = 'LIMIT: 9 PER ITEM'
            elif gesture == 'fist':
                if any(self.cart):
                    self.page, action = 'REVIEW', 'review'
                    self.review_selected = self.selected
                    self.select_cart_item()
                    self.message = 'CHECK YOUR ORDER'
                else:
                    self.message = 'CART EMPTY - ADD AN ITEM'
            elif gesture == 'victory':
                self.resume_page = self.page
                self.page, action = 'EXIT_CONFIRM', 'ask_exit'
                self.message = 'DISCARD THIS CART?'
        elif self.page == 'REVIEW':
            if gesture == 'open_palm':
                self.select_cart_item(advance=True)
                action = 'select_cart_item'
                self.message = 'ROW SELECTED' if any(self.cart) else 'CART EMPTY - V TO MENU'
            elif gesture == 'thumbs_up' and any(self.cart):
                order = dict(number=len(self.orders)+1, created_seconds=now,
                    items=[dict(id=item['id'], name=item['name'], quantity=qty,
                                unit_price_fen=item['price_fen'])
                           for item, qty in zip(self.menu, self.cart) if qty],
                    total_fen=self.total_fen, simulated=True, paid=False)
                # Publish success only AFTER the storage callback completes.
                if self.save_order is not None:
                    self.save_order(deepcopy(order))
                self.orders.append(order)
                self.page, action = 'DONE', 'submit_demo_order'
                self.message = 'DEMO ORDER SAVED - NO PAYMENT'
            elif gesture == 'victory':
                self.page, action = 'MENU', 'back_to_menu'
                self.message = 'CONTINUE ORDERING'
            elif gesture == 'fist':
                self.select_cart_item()
                if self.review_selected is not None:
                    removed = self.review_selected
                    self.cart[removed] -= 1
                    action = 'remove_one'
                    self.message = 'REMOVED 1 '+self.menu[removed]['name']
                    self.select_cart_item()
                if not any(self.cart):
                    self.message = 'CART EMPTY - V TO MENU'
            elif gesture == 'thumbs_up':
                self.message = 'CART EMPTY - V TO MENU'
        elif self.page == 'EXIT_CONFIRM':
            if gesture == 'thumbs_up':
                self.page, action = 'WELCOME', 'discard_cart'
                self.cart = [0]*len(self.menu)
                self.message = 'OPEN PALM TO START'
            elif gesture == 'victory':
                self.page, action = self.resume_page, 'cancel_exit'
                self.message = 'CART KEPT'
        if action != 'ignored':
            self.events.append(dict(at_seconds=now, gesture=gesture, action=action,
                                    before=before, after=self.page, total_fen=self.total_fen,
                                    cart=list(self.cart), selected=self.selected,
                                    review_selected=self.review_selected))
        return action

    def snapshot(self):
        return dict(page=self.page, selected=self.selected, cart=list(self.cart),
                    review_selected=self.review_selected,
                    total_fen=self.total_fen, message=self.message,
                    order_count=len(self.orders),
                    last_order=deepcopy(self.orders[-1]) if self.orders else None)
