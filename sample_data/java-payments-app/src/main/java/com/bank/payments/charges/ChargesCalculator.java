package com.bank.payments.charges;

import java.util.List;

/** Calculates transfer charges and checks the charge-bearer option (OUR, SHA, BEN). */
public class ChargesCalculator {
    private static final List<String> OPTIONS = List.of("OUR", "SHA", "BEN");

    public boolean isSupportedOption(String option) {
        return option != null && OPTIONS.contains(option);
    }

    public double calculate(double amount, String option) {
        double fee = Math.max(5.0, amount * 0.001);
        return "BEN".equals(option) ? 0.0 : fee;
    }
}
