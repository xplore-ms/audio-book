from app.domain.payment import repository as payment_repo


def process_payment(payment_data):
    # Placeholder to wrap payment gateway clients
    return payment_repo.record_payment(payment_data)
