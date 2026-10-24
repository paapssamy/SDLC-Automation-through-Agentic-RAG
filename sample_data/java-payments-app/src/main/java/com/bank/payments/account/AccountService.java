package com.bank.payments.account;

import java.util.HashMap;
import java.util.Map;

/** Holds customer account balances and performs debits. */
public class AccountService {
    private final Map<String, Double> balances = new HashMap<>();

    public double getBalance(String account) {
        return balances.getOrDefault(account, 0.0);
    }

    public void debit(String account, double amount) {
        double balance = getBalance(account);
        if (balance < amount) {
            throw new IllegalStateException("Insufficient funds");
        }
        balances.put(account, balance - amount);
    }
}
