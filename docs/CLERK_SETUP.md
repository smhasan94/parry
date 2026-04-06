# Clerk Authentication Setup

Parry uses [Clerk](https://clerk.com) for user authentication and organization management.

## Prerequisites

1. Create a Clerk account at https://clerk.com
2. Create a new Clerk application

## Configuration

### 1. Get your API keys

From the Clerk dashboard, go to **API Keys** and copy:

- **Publishable Key** (`pk_test_...` or `pk_live_...`)
- **Secret Key** (`sk_test_...` or `sk_live_...`)

Add these to your `.env` file:

```env
CLERK_SECRET_KEY=sk_test_...
CLERK_PUBLISHABLE_KEY=pk_test_...
VITE_CLERK_PUBLISHABLE_KEY=pk_test_...
```

### 2. Configure webhook

Clerk webhooks sync user and organization events to the Parry backend.

1. In Clerk dashboard, go to **Webhooks**
2. Click **Add Endpoint**
3. Set the URL to: `https://your-domain.com/api/v1/webhooks/clerk`
4. Select these events:
   - `organization.created`
   - `organization.updated`
   - `organization.deleted`
   - `user.created`
5. Copy the **Signing Secret** and add to `.env`:

```env
CLERK_WEBHOOK_SECRET=whsec_...
```

### 3. Enable Organizations

1. In Clerk dashboard, go to **Organizations**
2. Enable the Organizations feature
3. This allows users to create and manage teams

## How it works

- **User signs up** → Clerk sends `user.created` webhook → Parry creates a personal workspace org
- **User creates org** → Clerk sends `organization.created` webhook → Parry creates the org record
- **Dashboard auth** → Clerk JWT in `Authorization: Bearer` header → Backend verifies via JWKS
- **SDK auth** → API key in `X-Parry-Secret` header → Backend verifies via SHA256 hash lookup

## Local development

For local development without Clerk:
1. Leave `CLERK_SECRET_KEY` empty in `.env`
2. The backend falls back to a demo org for all requests
3. Dashboard will show the Clerk sign-in UI but won't work without a valid publishable key

## Troubleshooting

- **Webhook not received**: Check the webhook URL matches your deployed backend URL
- **401 on dashboard API calls**: Verify `VITE_CLERK_PUBLISHABLE_KEY` matches `CLERK_PUBLISHABLE_KEY`
- **Org not created after signup**: Check webhook logs in Clerk dashboard for delivery failures
