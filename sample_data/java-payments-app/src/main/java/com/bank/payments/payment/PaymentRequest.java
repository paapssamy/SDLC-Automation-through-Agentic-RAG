package com.bank.payments.payment;

/** Customer credit transfer request. */
public class PaymentRequest {
    private String reference;
    private String debtorAccount;
    private String creditorAccount;
    private String creditorCountry;
    private String chargesOption;
    private Amount amount;

    public String getReference() { return reference; }
    public String getDebtorAccount() { return debtorAccount; }
    public String getCreditorAccount() { return creditorAccount; }
    public String getCreditorCountry() { return creditorCountry; }
    public String getChargesOption() { return chargesOption; }
    public Amount getAmount() { return amount; }

    /** Amount with currency. */
    public static class Amount {
        private final double value;
        private final String currency;

        public Amount(double value, String currency) {
            this.value = value;
            this.currency = currency;
        }

        public double getValue() { return value; }
        public String getCurrency() { return currency; }
    }
}
