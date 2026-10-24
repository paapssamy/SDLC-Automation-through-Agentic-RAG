package com.bank.payments.cutoff;

import java.time.LocalTime;

/** Decides whether a payment is processed today or on the next business day. */
public class CutOffTimeService {
    private static final LocalTime SGD_CUTOFF = LocalTime.of(15, 0);
    private static final double HIGH_VALUE_LIMIT = 1_000_000.0;

    public boolean isBeforeCutOff(String currency, double amount, LocalTime now) {
        return now.isBefore(getCutOff(currency, amount));
    }

    public LocalTime getCutOff(String currency, double amount) {
        if ("SGD".equals(currency) && amount >= HIGH_VALUE_LIMIT) {
            return SGD_CUTOFF.minusHours(1);
        }
        return SGD_CUTOFF;
    }
}
