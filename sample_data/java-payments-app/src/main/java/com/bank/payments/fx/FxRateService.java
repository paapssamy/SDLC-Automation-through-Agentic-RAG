package com.bank.payments.fx;

import java.util.Map;

/** Provides indicative foreign exchange rates against SGD. */
public class FxRateService {
    private final Map<String, Double> ratesToSgd = Map.of("USD", 1.35, "EUR", 1.46, "SGD", 1.0);

    public double getRate(String fromCurrency, String toCurrency) {
        return ratesToSgd.getOrDefault(fromCurrency, 1.0) / ratesToSgd.getOrDefault(toCurrency, 1.0);
    }

    public double convert(double amount, String fromCurrency, String toCurrency) {
        return amount * getRate(fromCurrency, toCurrency);
    }
}
