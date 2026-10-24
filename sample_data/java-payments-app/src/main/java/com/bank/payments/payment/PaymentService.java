package com.bank.payments.payment;

import com.bank.payments.account.AccountService;
import com.bank.payments.messaging.Pacs008MessageBuilder;
import com.bank.payments.notification.PaymentStatusNotifier;
import com.bank.payments.persistence.PaymentRepository;
import com.bank.payments.screening.SanctionsScreeningService;
import com.bank.payments.validation.PaymentValidator;

/** Orchestrates validation, screening, message creation and persistence of a payment. */
public class PaymentService {
    private final PaymentValidator validator;
    private final SanctionsScreeningService screening;
    private final Pacs008MessageBuilder messageBuilder;
    private final PaymentRepository repository;
    private final AccountService accountService;
    private final PaymentStatusNotifier notifier;

    public PaymentService(PaymentValidator validator, SanctionsScreeningService screening,
                          Pacs008MessageBuilder messageBuilder, PaymentRepository repository,
                          AccountService accountService, PaymentStatusNotifier notifier) {
        this.validator = validator;
        this.screening = screening;
        this.messageBuilder = messageBuilder;
        this.repository = repository;
        this.accountService = accountService;
        this.notifier = notifier;
    }

    public PaymentStatus process(PaymentRequest request) {
        if (!validator.validate(request)) {
            return finish(request, PaymentStatus.REJECTED);
        }
        if (screening.isBlocked(request.getCreditorCountry())) {
            return finish(request, PaymentStatus.REJECTED);
        }
        accountService.debit(request.getDebtorAccount(), request.getAmount().getValue());
        String message = messageBuilder.build(request);
        repository.save(request.getReference(), message);
        return finish(request, PaymentStatus.SENT);
    }

    public PaymentStatus findStatus(String reference) {
        return repository.findStatus(reference);
    }

    private PaymentStatus finish(PaymentRequest request, PaymentStatus status) {
        repository.updateStatus(request.getReference(), status);
        notifier.notifyStatus(request.getReference(), status);
        return status;
    }
}
