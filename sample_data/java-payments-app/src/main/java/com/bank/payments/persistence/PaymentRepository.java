package com.bank.payments.persistence;

import com.bank.payments.payment.PaymentStatus;

/** Storage of payments and their messages. */
public interface PaymentRepository {
    void save(String reference, String message);

    void updateStatus(String reference, PaymentStatus status);

    PaymentStatus findStatus(String reference);
}
