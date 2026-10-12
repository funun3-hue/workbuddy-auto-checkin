"""WorkBuddy template matching with light-theme templates and dark-theme fallbacks."""
from pathlib import Path
import ctypes
import time
import cv2
import numpy as np
from PIL import ImageGrab
import win32gui
import win32process

ASSETS = Path(__file__).resolve().parent / 'assets'
MATCH_THRESHOLD = .92
POLL_SECONDS = .1
SUCCESS_CONFIRM_TIMEOUT_SECONDS = 10
# Coordinates within the supplied full header crops, not their image centers.
CLOSE_TARGETS = {
    'checkin-close-light.png': (198, 17),
    'checkin-close-dark.png': (199, 16),
}


def load_template(name):
    data = np.fromfile(ASSETS / name, dtype=np.uint8)
    template = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if template is None or float(template.std()) < 5:
        raise RuntimeError(f'Invalid image template: {name}')
    return template


def locate(frame, template, threshold=MATCH_THRESHOLD):
    """Return a unique center and score; do not guess between repeated labels."""
    h, w = template.shape
    if frame.shape[0] < h or frame.shape[1] < w:
        return None
    scores = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
    _, best, _, pos = cv2.minMaxLoc(scores)
    if best < threshold:
        return None
    x, y = pos
    # Suppress the same match's neighboring peaks, then check for another copy.
    scores[max(0,y-h//2):y+h//2+1, max(0,x-w//2):x+w//2+1] = -1
    if cv2.minMaxLoc(scores)[1] >= threshold:
        raise RuntimeError('Multiple matching buttons in WorkBuddy; no click performed')
    return ((x+w//2, y+h//2), float(best))


class ImageLocator:
    def __init__(self, hwnd, logger):
        self.hwnd = hwnd
        self.logger = logger
        self.templates = {
            name: load_template(name)
            for name in (
                'claim-light.png',
                'claim.png',
                'avatar-anchor-light.png',
                'avatar-anchor.png',
                'buddy-entry-light.png',
                'buddy-entry.png',
                'claim-menu-light.png',
                'claim-menu.png',
                'claimed-today-light.png',
                'claimed-today.png',
                'checkin-close-light.png',
                'checkin-close-dark.png',
            )
        }

    def same_process_window(self, candidate):
        if not candidate or not win32gui.IsWindow(candidate):
            return False
        return (
            win32process.GetWindowThreadProcessId(candidate)[1]
            == win32process.GetWindowThreadProcessId(self.hwnd)[1]
        )

    def check_foreground(self):
        foreground = win32gui.GetForegroundWindow()
        if win32gui.IsWindow(self.hwnd) and (
            foreground == self.hwnd or self.same_process_window(foreground)
        ):
            return
        # A notification, an update popup or another app can steal the foreground
        # while we are waiting for a template. Every click target lives inside
        # WorkBuddy, so take the foreground back once before giving up.
        try:
            ctypes.windll.user32.SetForegroundWindow(self.hwnd)
        except Exception:
            pass
        time.sleep(0.2)
        foreground = win32gui.GetForegroundWindow()
        if foreground == self.hwnd or self.same_process_window(foreground):
            self.logger.info('recovered the foreground after another window took it')
            return
        raise RuntimeError('WorkBuddy lost foreground; image clicks stopped')

    def client_rect(self):
        left, top = win32gui.ClientToScreen(self.hwnd, (0,0))
        _, _, width, height = win32gui.GetClientRect(self.hwnd)
        if width < 300 or height < 200:
            raise RuntimeError('WorkBuddy window is not ready')
        return (left, top, left+width, top+height)

    def find_any(self, names, timeout=0):
        """Find the first matching template, in the supplied priority order."""
        deadline = time.monotonic() + timeout
        while True:
            self.check_foreground()
            box = self.client_rect()
            start = time.monotonic()
            frame = cv2.cvtColor(np.asarray(ImageGrab.grab(bbox=box, all_screens=True)), cv2.COLOR_RGB2GRAY)
            matched_name = None
            match = None
            for name in names:
                candidate = locate(frame, self.templates[name])
                if candidate is not None and name in CLOSE_TARGETS:
                    (cx, cy), _ = candidate
                    template = self.templates[name]
                    h, w = template.shape
                    region = frame[cy-h//2:cy-h//2+h, cx-w//2:cx-w//2+w]
                    # Normalized matching alone can confuse light/dark headers.
                    if abs(float(region.mean()) - float(template.mean())) > 20:
                        candidate = None
                if candidate is not None:
                    matched_name = name
                    match = candidate
                    break
            self.check_foreground()
            if match is not None and self.client_rect() == box:
                (x,y), score = match
                if matched_name in CLOSE_TARGETS:
                    h, w = self.templates[matched_name].shape
                    dx, dy = CLOSE_TARGETS[matched_name]
                    x, y = x-w//2+dx, y-h//2+dy
                point = (box[0]+x,box[1]+y)
                self.logger.info('image matched %s score=%.3f elapsed=%.3fs center=%s', matched_name, score, time.monotonic()-start, point)
                return point
            if time.monotonic() >= deadline:
                return None
            time.sleep(POLL_SECONDS)

    def find(self, name, timeout=0):
        return self.find_any((name,), timeout)

    def click_point(self, click_screen, point):
        self.check_foreground()
        # A floating window can cover WorkBuddy without changing its foreground.
        hit = win32gui.WindowFromPoint(point)
        top_level = win32gui.GetAncestor(hit, 2)
        if top_level != self.hwnd and not self.same_process_window(top_level):
            raise RuntimeError('WorkBuddy target is covered by another window')
        click_screen(*point)

    def click_images(self, click_screen, names, timeout=10):
        point = self.find_any(names, timeout)
        if point is None:
            raise RuntimeError(f'WorkBuddy images not found: {", ".join(names)}; window left open')
        self.click_point(click_screen, point)
        return point


def perform(hwnd, logger, click_screen):
    locator = ImageLocator(hwnd, logger)
    points = []
    # One immediate search; only a missing target triggers the avatar route.
    claim = locator.find_any(('claim-light.png', 'claim.png'))
    if claim is not None:
        locator.click_point(click_screen, claim)
        points.append(claim)
        route = 'direct_image'
    else:
        points.append(locator.click_images(
            click_screen, ('avatar-anchor-light.png', 'avatar-anchor.png')
        ))
        points.append(locator.click_images(
            click_screen, ('buddy-entry-light.png', 'buddy-entry.png')
        ))
        points.append(locator.click_images(
            # WorkBuddy also renders this panel with the plain claim-button
            # background. Match both supplied variants after opening Buddy.
            click_screen, (
                'claim-menu-light.png', 'claim-menu.png',
                'claim-light.png', 'claim.png',
            )
        ))
        route = 'avatar_entry_claim_images'
    time.sleep(2.0)
    # Record success while the check-in panel is still visible.
    confirmation = locator.find_any(('claimed-today-light.png', 'claimed-today.png'))
    close_position = locator.find_any(
        tuple(CLOSE_TARGETS), SUCCESS_CONFIRM_TIMEOUT_SECONDS,
    )
    if close_position is not None:
        locator.click_point(click_screen, close_position)
        logger.info('closed the check-in panel at cross center %s', close_position)
    else:
        logger.warning('check-in panel close images not found; no close click performed')
    if confirmation is None:
        confirmation = locator.find_any(
            ('claimed-today-light.png', 'claimed-today.png'),
            SUCCESS_CONFIRM_TIMEOUT_SECONDS,
        )
    confirmed = confirmation is not None
    if confirmed:
        logger.info('WorkBuddy claim confirmed by a today-claimed image at %s', confirmation)
    else:
        logger.warning('WorkBuddy claim was clicked but not confirmed within %.1fs', SUCCESS_CONFIRM_TIMEOUT_SECONDS)
    return {
        'status': 'claim_image_clicked',
        'route': route,
        'positions': points,
        'confirmation_position': confirmation,
        'checkin_panel_close_position': close_position,
        'checkin_panel_closed': close_position is not None,
        'checkin_verified': confirmed,
    }
