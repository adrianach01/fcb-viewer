import unittest
from datetime import datetime

from fcb_viewer import (
    MADRID_TZ,
    classify_status,
    decide_notification,
    locale_from_url,
    should_send_heartbeat,
)

EN_URL = "https://www.fcbarcelona.com/en/tickets/football/regular/laliga/fcbarcelona-realmadrid"
ES_URL = "https://www.fcbarcelona.es/es/entradas/futbol/regular/laliga/fcbarcelona-athleticclub"

EVENT = {"id": "fcb-test", "title": "⚽ FC Barcelona 🆚 Test", "url": EN_URL}


def madrid(*args, **kwargs):
    return datetime(*args, tzinfo=MADRID_TZ, **kwargs)


class LocaleFromUrlTests(unittest.TestCase):
    def test_english_url(self):
        self.assertEqual(locale_from_url(EN_URL), "en")

    def test_spanish_url(self):
        self.assertEqual(locale_from_url(ES_URL), "es")

    def test_unknown_locale_raises(self):
        with self.assertRaises(ValueError):
            locale_from_url("https://www.fcbarcelona.com/fr/billets/foo")


class ClassifyStatusTests(unittest.TestCase):
    def test_english_buyable_real_link(self):
        buttons = [{
            "text": "BUY TICKETS",
            "href": "https://go.fcbarcelona.com/SOMETHING",
            "classes": "button-buy dtm-event-trigger",
        }]
        self.assertEqual(classify_status(buttons, "en"), "buyable")

    def test_english_unavailable(self):
        buttons = [{
            "text": "TEMPORARILY UNAVAILABLE",
            "href": "",
            "classes": "button-buy",
        }]
        self.assertEqual(classify_status(buttons, "en"), "unavailable")

    def test_english_not_available_with_real_href_is_still_unavailable(self):
        # Confirmed live on fcbarcelona.com: text is "NOT AVAILABLE" (not
        # "TEMPORARILY UNAVAILABLE") and the href is a real purchase URL even
        # though the button is disabled via the btn--disabled class.
        buttons = [{
            "text": "NOT AVAILABLE",
            "href": "https://go.fcbarcelona.com/SPOTIFYCAMPNOU/BASIC/FCBARCELONA-REALMADRID2627/EN",
            "classes": "button-buy   dtm-event-trigger btn--disabled button-outline-blue",
        }]
        self.assertEqual(classify_status(buttons, "en"), "unavailable")

    def test_spanish_no_disponible_with_real_href_is_still_unavailable(self):
        buttons = [{
            "text": "NO DISPONIBLE",
            "href": "https://go.fcbarcelona.com/SPOTIFYCAMPNOU/BASIC/FCBARCELONA-REALMADRID2627/ES",
            "classes": "button-buy   dtm-event-trigger btn--disabled button-outline-blue",
        }]
        self.assertEqual(classify_status(buttons, "es"), "unavailable")

    def test_spanish_buy_text_but_hash_href_and_modal_is_pending_not_buyable(self):
        buttons = [{
            "text": "COMPRAR ENTRADAS",
            "href": "#",
            "classes": "button-buy  modal-activate dtm-event-trigger  ",
        }]
        self.assertEqual(classify_status(buttons, "es"), "unavailable")

    def test_spanish_buyable_real_link(self):
        buttons = [{
            "text": "COMPRAR ENTRADAS",
            "href": "https://go.fcbarcelona.com/SPOTIFYCAMPNOU/BASICPLUS/FCBARCELONA-ATHLETICCLUB2627/ES",
            "classes": "button-buy   dtm-event-trigger  ",
        }]
        self.assertEqual(classify_status(buttons, "es"), "buyable")

    def test_spanish_unavailable_class(self):
        buttons = [{
            "text": "COMPRAR ENTRADAS",
            "href": "#",
            "classes": "button-buy button-buy__non-available",
        }]
        self.assertEqual(classify_status(buttons, "es"), "unavailable")

    def test_no_buttons_is_unknown(self):
        self.assertEqual(classify_status([], "en"), "unknown")

    def test_buyable_wins_over_unavailable(self):
        buttons = [
            {"text": "TEMPORARILY UNAVAILABLE", "href": "", "classes": "button-buy"},
            {"text": "BUY TICKETS", "href": "https://go.fcbarcelona.com/X", "classes": "button-buy"},
        ]
        self.assertEqual(classify_status(buttons, "en"), "buyable")


class ShouldSendHeartbeatTests(unittest.TestCase):
    def test_no_previous_notification_sends(self):
        self.assertTrue(should_send_heartbeat({"last_notified_at": None}, madrid(2026, 7, 20, 12, 0)))

    def test_same_day_does_not_send(self):
        prev = {"last_notified_at": madrid(2026, 7, 20, 9, 0).isoformat()}
        self.assertFalse(should_send_heartbeat(prev, madrid(2026, 7, 20, 15, 0)))

    def test_next_day_before_threshold_does_not_send(self):
        prev = {"last_notified_at": madrid(2026, 7, 20, 9, 0).isoformat()}
        self.assertFalse(should_send_heartbeat(prev, madrid(2026, 7, 21, 10, 0)))

    def test_next_day_after_threshold_sends(self):
        prev = {"last_notified_at": madrid(2026, 7, 20, 9, 0).isoformat()}
        self.assertTrue(should_send_heartbeat(prev, madrid(2026, 7, 21, 10, 31)))


class DecideNotificationTests(unittest.TestCase):
    def test_flip_to_buyable_notifies_immediately(self):
        prev = {"status": "unavailable", "last_notified_at": None}
        notify, message, new_status, _ = decide_notification(EVENT, "buyable", prev, madrid(2026, 7, 20, 9, 0))
        self.assertTrue(notify)
        self.assertIsNotNone(message)
        self.assertEqual(new_status, "buyable")

    def test_repeat_buyable_same_day_is_silent(self):
        prev = {"status": "buyable", "last_notified_at": madrid(2026, 7, 20, 9, 0).isoformat()}
        notify, message, _, _ = decide_notification(EVENT, "buyable", prev, madrid(2026, 7, 20, 15, 0))
        self.assertFalse(notify)
        self.assertIsNone(message)

    def test_repeat_buyable_next_day_after_threshold_sends_heartbeat(self):
        prev = {"status": "buyable", "last_notified_at": madrid(2026, 7, 20, 9, 0).isoformat()}
        notify, message, _, _ = decide_notification(EVENT, "buyable", prev, madrid(2026, 7, 21, 10, 31))
        self.assertTrue(notify)
        self.assertIsNotNone(message)

    def test_buyable_to_unavailable_regression_notifies(self):
        prev = {"status": "buyable", "last_notified_at": madrid(2026, 7, 20, 9, 0).isoformat()}
        notify, message, new_status, _ = decide_notification(EVENT, "unavailable", prev, madrid(2026, 7, 20, 15, 0))
        self.assertTrue(notify)
        self.assertIsNotNone(message)
        self.assertEqual(new_status, "unavailable")

    def test_repeat_unavailable_is_silent(self):
        prev = {"status": "unavailable", "last_notified_at": None}
        notify, message, _, _ = decide_notification(EVENT, "unavailable", prev, madrid(2026, 7, 20, 15, 0))
        self.assertFalse(notify)
        self.assertIsNone(message)

    def test_repeat_unknown_is_gated_by_heartbeat(self):
        prev = {"status": "unknown", "last_notified_at": madrid(2026, 7, 20, 9, 0).isoformat()}
        notify_same_day, _, _, _ = decide_notification(EVENT, "unknown", prev, madrid(2026, 7, 20, 15, 0))
        notify_next_day, _, _, _ = decide_notification(EVENT, "unknown", prev, madrid(2026, 7, 21, 10, 31))
        self.assertFalse(notify_same_day)
        self.assertTrue(notify_next_day)


if __name__ == "__main__":
    unittest.main()
