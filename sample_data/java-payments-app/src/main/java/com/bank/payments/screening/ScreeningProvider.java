package com.bank.payments.screening;

/** Source of sanctioned country codes. */
public interface ScreeningProvider {
    boolean isCountrySanctioned(String countryCode);
}
