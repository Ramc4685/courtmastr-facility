import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import * as Crypto from 'expo-crypto';
import { useRef, useState } from 'react';
import { Alert } from 'react-native';

import { portal, type PortalInvoice } from '../adapters';
import { useApp } from '../lib/app-state';
import { clientName, useHousehold } from '../lib/household';
import { formatDate, formatMoney } from '../ui/format';
import { Badge, Body, Button, DemoBanner, Empty, ErrorBox, Heading, Loading, Screen, Small, Surface } from '../ui/kit';
import { ProfileSwitcher } from '../ui/ProfileSwitcher';

const tone = (i: PortalInvoice) => (i.status === 'paid' ? 'success' : i.is_past_due ? 'danger' : i.status === 'voided' ? 'neutral' : 'warning');

export default function Invoices() {
  const { tenant } = useApp();
  const { actingFor } = useHousehold();
  const qc = useQueryClient();
  const clientId = actingFor?.client.id;
  const currency = 'USD';
  const invoices = useQuery({ queryKey: ['invoices', tenant?.slug, clientId], queryFn: () => portal.listInvoices(clientId!), enabled: !!clientId });
  const methods = useQuery({ queryKey: ['payment-methods', tenant?.slug], queryFn: () => portal.listPaymentMethods() });
  const keys = useRef(new Map<string, string>());
  const [notice, setNotice] = useState<string | null>(null);

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
      setNotice(
        payment.status === 'succeeded'
          ? `Paid invoice #${invoice.number}. Receipt #${payment.receipt_number}.`
          : payment.next_action
            ? 'Your bank needs to confirm this payment. In-app card confirmation arrives with the payment sheet; finish it on the web portal for now.'
            : `Payment is ${payment.status}.`,
      );
      void qc.invalidateQueries({ queryKey: ['invoices'] });
    },
  });

  const method = methods.data?.[0];
  const confirm = (invoice: PortalInvoice) =>
    Alert.alert(
      `Pay ${formatMoney(invoice.balance_minor, currency)}?`,
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
      {invoices.isLoading ? <Loading /> : invoices.error ? <ErrorBox error={invoices.error} /> : !invoices.data?.length ? <Empty text="No invoices." /> : invoices.data.map((inv) => (
        <Surface key={inv.id}>
          <Body>Invoice #{inv.number}</Body>
          <Badge label={inv.is_past_due ? 'Past due' : inv.status.replace('_', ' ')} tone={tone(inv)} />
          {inv.charges.map((c) => (
            <Small key={c.id}>
              {c.description} · {formatMoney(c.total_minor, currency)}
            </Small>
          ))}
          <Small>Issued {formatDate(inv.invoice_on)} · due {formatDate(inv.due_on)}</Small>
          <Body>
            Total {formatMoney(inv.total_minor, currency)}
            {inv.balance_minor > 0 ? ` · ${formatMoney(inv.balance_minor, currency)} due` : ''}
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
