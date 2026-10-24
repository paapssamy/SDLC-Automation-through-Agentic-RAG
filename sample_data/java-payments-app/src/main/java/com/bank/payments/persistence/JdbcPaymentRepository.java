package com.bank.payments.persistence;

import com.bank.payments.payment.PaymentStatus;
import java.util.HashMap;
import java.util.Map;

/** JDBC-style implementation (in-memory for the demo). */
public class JdbcPaymentRepository implements PaymentRepository {
    private final Map<String, String> messages = new HashMap<>();
    private final Map<String, PaymentStatus> statuses = new HashMap<>();

    @Override
    public void save(String reference, String message) {
        messages.put(reference, message);
        statuses.put(reference, PaymentStatus.SENT);
    }

    @Override
    public void updateStatus(String reference, PaymentStatus status) {
        statuses.put(reference, status);
    }

    @Override
    public PaymentStatus findStatus(String reference) {
        return statuses.get(reference);
    }
}
