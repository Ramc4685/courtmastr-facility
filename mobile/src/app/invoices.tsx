import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import * as Crypto from 'expo-crypto';
import { useRef, useState } from 'react';
import { Alert } from 'react-native';

import { portal, type PortalInvoice, type PortalPayment } from '../adapters';
import { useApp } from '../lib/app-state';
import { useAppConfig } from '../lib/hooks';
import { clientName, useHousehold } from '../lib/household';
import { formatDate, formatMoney } from '../ui/format';
import { Badge, Body, Button, DemoBanner, Empty, ErrorBox, Heading, Loading, Screen, Small, Surface } from '../ui/kit';
import { useCheckoutProvider } from '../ui/NewCard';
import { ProfileSwitcher } from '../ui/ProfileSwitcher';

const tone = (i: PortalInvoice) => (i.status === 'paid' ? 'success' : i.is_past_due ? 'danger' : i.status === 'voided' ? 'neutral' : 'warning');

export default function Invoices() {
  const { tenant } = useApp();
  const { actingFor } = useHousehold();
  const qc = useQueryClient();
  const clientId = actingFor?.client.id;
  // The facility's currency from the app config; amounts wait for it rather than guess one.
  const currency = useAppConfig().data?.currency;
  const money = (minor: number) => (currency ? formatMoney(minor, currency) : '…');
  const invoices = useQuery({ queryKey: ['invoices', tenant?.slug, clientId], queryFn: () => portal.listInvoices(clientId!), enabled: !!clientId });
  const methods = useQuery({ queryKey: ['payment-methods', tenant?.slug], queryFn: () => portal.listPaymentMethods() });
  const keys = useRef(new Map<string, string>());
  const [notice, setNotice] = useState<string | null>(null);
  const [check, setCheck] = useState<{ payment: PortalPayment; invoice: PortalInvoice } | null>(null);
  const provider = useCheckoutProvider();
  const paid = (payment: PortalPayment, invoice: PortalInvoice) =>
    setNotice(payment.status === 'succeeded' ? `Paid invoice #${invoice.number}. Receipt #${payment.receipt_number}.` : `Payment is ${payment.status.replace(/_/g, ' ')}.`);

  const pay = useMutation({
    mutationFn: (invoice: PortalInvoice) => {
      const method = methods.data?.[0];
      if (!method) throw new Error('Add a payment method on the web portal first.');
      const idempotencyKey = keys.current.get(invoice.id) ?? Crypto.randomUUID();
      keys.current.set(invoice.id, idempotencyKey);
      return portal.payInvoices({ invoiceIds: [invoice.id], paymentMethodId: method.id, idempotencyKey });
    },
    onSuccess: (payment, invoice) => {
      keys.current.delete(invoice.id);
      if (payment.next_action?.client_secret) {
        setNotice(null);
        setCheck({ payment, invoice });
      } else paid(payment, invoice);
      void qc.invalidateQueries({ queryKey: ['invoices'] });
    },
  });
  // The bank's check (3-D Secure), then confirmPortalPayment re-reads the payment and applies it.
  const authenticate = useMutation({
    mutationFn: async (approve: boolean) => {
      const { payment, invoice } = check!;
      await portal.authenticatePayment({ clientSecret: payment.next_action!.client_secret!, approve });
      return portal.confirmPayment({ paymentId: payment.id, invoiceIds: [invoice.id], idempotencyKey: Crypto.randomUUID() });
    },
    onSuccess: (payment) => {
      paid(payment, check!.invoice);
      setCheck(null);
      void qc.invalidateQueries({ queryKey: ['invoices'] });
    },
  });

  const method = methods.data?.[0];
  const confirm = (invoice: PortalInvoice) =>
    Alert.alert(
      `Pay ${money(invoice.balance_minor)}?`,
      `Invoice #${invoice.number}, charged to ${method ? `${method.brand ?? method.kind} ending ${method.last4}` : 'your saved method'}. Payment always uses your own account.`,
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Pay now', onPress: () => pay.mutate(invoice) },
      ],
    );

  return (
    <Screen onRefresh={() => void invoices.refetch()} refreshing={invoices.isRefetching}>
      {portal.isDemo && <DemoBanner waitingOn="portal billing (GET /portal/invoices, POST /portal/payments)" />}
      <ProfileSwitcher />
      {actingFor && <Heading>Billed to {clientName(actingFor)}</Heading>}
      {notice && <Body>{notice}</Body>}
      {pay.error ? <ErrorBox error={pay.error} /> : null}
      {check && (
        <Surface>
          <Body>Your bank asks you to confirm this payment. Nothing is charged until you do.</Body>
          {authenticate.error ? <ErrorBox error={authenticate.error} /> : null}
          {provider.data === 'fake' ? (
            <>
              <Button label="Approve as the bank (test)" onPress={() => authenticate.mutate(true)} loading={authenticate.isPending && authenticate.variables} />
              <Button variant="secondary" label="Fail the check (test)" onPress={() => authenticate.mutate(false)} loading={authenticate.isPending && !authenticate.variables} />
            </>
          ) : (
            <Small>Confirming with your bank in the app needs the card processor&apos;s sheet, which is not available yet. Finish it on the web portal.</Small>
          )}
        </Surface>
      )}
      {invoices.isLoading ? <Loading /> : invoices.error ? <ErrorBox error={invoices.error} /> : !invoices.data?.length ? <Empty text="No invoices." /> : invoices.data.map((inv) => (
        <Surface key={inv.id}>
          <Body>Invoice #{inv.number}</Body>
          <Badge label={inv.is_past_due ? 'Past due' : inv.status.replace('_', ' ')} tone={tone(inv)} />
          {inv.charges.map((c) => (
            <Small key={c.id}>
              {c.description} · {money(c.total_minor)}
            </Small>
          ))}
          <Small>Issued {formatDate(inv.invoice_on)} · due {formatDate(inv.due_on)}</Small>
          <Body>
            Total {money(inv.total_minor)}
            {inv.balance_minor > 0 ? ` · ${money(inv.balance_minor)} due` : ''}
          </Body>
          {inv.balance_minor > 0 && inv.status !== 'payment_pending' && (
            <Button compact label="Pay now" onPress={() => confirm(inv)} loading={pay.isPending && pay.variables?.id === inv.id} disabled={!method} />
          )}
        </Surface>
      ))}
      <Small>{method ? `Saved method: ${method.brand ?? method.kind} ending ${method.last4}.` : 'No saved payment method.'}</Small>
    </Screen>
  );
}
