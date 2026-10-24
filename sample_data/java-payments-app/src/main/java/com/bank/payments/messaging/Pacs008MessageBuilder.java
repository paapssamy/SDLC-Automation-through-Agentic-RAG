package com.bank.payments.messaging;

import com.bank.payments.payment.PaymentRequest;

/** Builds ISO 20022 pacs.008 FIToFICustomerCreditTransfer messages. */
public class Pacs008MessageBuilder {

    public String build(PaymentRequest request) {
        StringBuilder xml = new StringBuilder();
        xml.append("<Document><FIToFICstmrCdtTrf>");
        xml.append(groupHeader(request));
        xml.append(creditTransferInfo(request));
        xml.append("</FIToFICstmrCdtTrf></Document>");
        return xml.toString();
    }

    String groupHeader(PaymentRequest request) {
        return "<GrpHdr><MsgId>" + request.getReference() + "</MsgId><NbOfTxs>1</NbOfTxs></GrpHdr>";
    }

    String creditTransferInfo(PaymentRequest request) {
        return "<CdtTrfTxInf><IntrBkSttlmAmt Ccy=\"" + request.getAmount().getCurrency() + "\">"
                + request.getAmount().getValue() + "</IntrBkSttlmAmt>"
                + "<ChrgBr>" + request.getChargesOption() + "</ChrgBr>"
                + "<DbtrAcct>" + request.getDebtorAccount() + "</DbtrAcct>"
                + "<CdtrAcct>" + request.getCreditorAccount() + "</CdtrAcct></CdtTrfTxInf>";
    }
}
