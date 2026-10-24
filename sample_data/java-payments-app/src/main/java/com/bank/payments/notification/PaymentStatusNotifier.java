package com.bank.payments.notification;

import com.bank.payments.payment.PaymentStatus;

/** Informs the customer channel about payment status changes. */
public class PaymentStatusNotifier {

    public void notifyStatus(String reference, PaymentStatus status) {
        System.out.println("Notify customer: payment " + reference + " is " + status);
    }
}
