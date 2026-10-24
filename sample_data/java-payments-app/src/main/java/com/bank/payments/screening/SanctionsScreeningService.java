package com.bank.payments.screening;

import java.util.Set;

/** Screens payments against the sanctioned country list before they are released. */
public class SanctionsScreeningService implements ScreeningProvider {
    private static final Set<String> BLOCKED_COUNTRIES = Set.of("KP", "IR", "SY");

    public boolean isBlocked(String countryCode) {
        return isCountrySanctioned(countryCode);
    }

    @Override
    public boolean isCountrySanctioned(String countryCode) {
        return countryCode != null && BLOCKED_COUNTRIES.contains(countryCode.toUpperCase());
    }
}
