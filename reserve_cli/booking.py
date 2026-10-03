"""Plan meals and verify every write against the service's reservation list."""
from dataclasses import dataclass
from datetime import date, timedelta
import unicodedata

from .api import ApiError

# The original 2.5.0 app's date picker offers tomorrow through today + 3.
BOOKING_WINDOW_DAYS = 3
MEALS = {1: "breakfast", 2: "lunch", 3: "dinner"}


class BookingError(Exception):
    pass


def normalize(text):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", str(text)).casefold()
                            if not unicodedata.combining(c)).split())


def meal_number(row):
    labels = {"petit-dejeuner": 1, "breakfast": 1, "فطور": 1,
              "dejeuner": 2, "lunch": 2, "غداء": 2,
              "diner": 3, "dinner": 3, "عشاء": 3}
    for field in ("mealtype_fr", "mealtype_ar"):
        result = labels.get(normalize(row.get(field, "")))
        if result:
            return result
    raise BookingError("A reservation has an unknown meal type; stopped to avoid a duplicate.")


@dataclass(frozen=True)
class PlannedMeal:
    day: date
    meal: int
    depot: dict
    existing_id: int | None = None

    @property
    def key(self):
        return f"{self.day.isoformat()}:{self.meal}"

    @property
    def label(self):
        return MEALS[self.meal]


def matching_reservation(rows, item):
    matches = []
    for row in rows:
        if row.get("date_reserve") != item.day.isoformat():
            continue
        if meal_number(row) == item.meal:
            matches.append(row)
    if not matches:
        return None
    if len(matches) != 1:
        raise BookingError(f"Multiple reservations exist for {item.day} {item.label}; review in the app.")
    names = {normalize(item.depot.get(k, "")) for k in ("nameAR", "nameFR", "nameEN")} - {""}
    row = matches[0]
    actual = {normalize(row.get(k, "")) for k in ("depot_ar", "depot_fr")} - {""}
    if not names.intersection(actual):
        raise BookingError(f"{item.day} {item.label} is already reserved elsewhere. No cancellation was made.")
    if not row.get("id"):
        raise BookingError("An existing reservation is missing its confirmation ID.")
    return row


def make_plan(days, profile, depots, rows):
    locations = {int(d["id"]): d for d in depots}
    plan = []
    for day in sorted(set(days)):
        for meal in MEALS:
            # Python: Monday=0 ... Sunday=6. Lunch is Sunday through Thursday.
            if meal == 2 and day.weekday() in (4, 5):
                continue
            depot_id = profile["main_id"] if meal == 2 else profile["dorm_id"]
            if depot_id not in locations:
                raise BookingError("A configured restaurant is not offered to this account.")
            depot = locations[depot_id]
            if depot.get(MEALS[meal]) is not True:
                raise BookingError(f"The selected restaurant does not offer {MEALS[meal]}.")
            item = PlannedMeal(day, meal, depot)
            match = matching_reservation(rows, item)
            plan.append(PlannedMeal(day, meal, depot, int(match["id"]) if match else None))
    return plan


def order_dates(order, today):
    start = today + timedelta(days=1)
    if order["kind"] == "days":
        end = today + timedelta(days=order["days"])
    else:
        end = date.fromisoformat(order["until"])
    eligible_end = min(end, today + timedelta(days=BOOKING_WINDOW_DAYS))
    dates = [start + timedelta(days=i) for i in range(max(0, (eligible_end - start).days + 1))]
    return dates, max(0, (end - max(eligible_end, today)).days)


def apply_plan(client, store, plan, emit=print):
    journal = store.read("journal", {})
    # Check the complete plan before the first write.
    for item in plan:
        if not item.existing_id and journal.get(item.key, {}).get("state") == "pending":
            raise BookingError(f"{item.day} {item.label} has an unconfirmed earlier attempt. "
                               "Check the official app before using clear-pending.")
    for item in plan:
        if item.existing_id:
            journal[item.key] = {"state": "confirmed", "id": item.existing_id, "depot": item.depot["id"]}
            store.write("journal", journal)
            emit(f"Already reserved: {item.day} {item.label} (#{item.existing_id}).")
            continue
        # Refresh immediately before each write to notice bookings from the phone.
        match = matching_reservation(client.reservations(), item)
        if match:
            journal[item.key] = {"state": "confirmed", "id": match["id"], "depot": item.depot["id"]}
            store.write("journal", journal)
            emit(f"Already reserved: {item.day} {item.label} (#{match['id']}).")
            continue
        journal[item.key] = {"state": "pending", "depot": item.depot["id"]}
        store.write("journal", journal)
        failure = None
        result = None
        try:
            result = client.reserve(item.day.isoformat(), item.meal, item.depot["id"])
        except ApiError as exc:
            failure = exc
        # A timeout or a success response alone cannot establish the outcome.
        try:
            match = matching_reservation(client.reservations(), item)
        except (ApiError, BookingError):
            raise BookingError(f"Could not verify {item.day} {item.label}. The attempt is saved as pending; "
                               "it will not be submitted again automatically.") from None
        if not match:
            rejected = isinstance(result, dict) and (
                result.get("success") is False or
                any(row.get("status") is False for row in result.get("data", []) if isinstance(row, dict)))
            if rejected:
                journal[item.key]["state"] = "rejected"
                store.write("journal", journal)
                raise BookingError(f"The service rejected {item.day} {item.label}. No reservation was confirmed.")
            suffix = " after a network/service error" if failure else ""
            raise BookingError(f"{item.day} {item.label} remains unconfirmed{suffix}; automatic resubmission is blocked.")
        journal[item.key] = {"state": "confirmed", "id": match["id"], "depot": item.depot["id"]}
        store.write("journal", journal)
        emit(f"Confirmed: {item.day} {item.label} (#{match['id']}).")
