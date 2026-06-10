# Deployment

This project has one Django backend and two Vite/Vue frontends.

## Backend on Render

1. Open Render and create a new Blueprint from this GitHub repository.
2. Render reads `render.yaml` and creates:
   - `aiapp-backend`
   - `aiapp-db`
3. After the first deploy finishes, copy the backend public URL, for example:
   `https://aiapp-backend.onrender.com`
4. In the backend service environment variables, set production values as needed:
   - `ADMIN_USER`
   - `ADMIN_PASSWORD`
   - `AI_API_KEY`
   - `SITE_BASE_URL`
   - `FRONTEND_USER_URL`
   - Alipay variables if payment is enabled

## Frontends on Vercel

Create two Vercel projects from this same GitHub repository.

### User frontend

- Root Directory: `frontend-user`
- Build Command: `npm run build`
- Output Directory: `dist`
- Environment Variable:
  - `VITE_API_BASE_URL=https://your-render-backend-url`

### Admin frontend

- Root Directory: `frontend-admin`
- Build Command: `npm run build`
- Output Directory: `dist`
- Environment Variable:
  - `VITE_API_BASE_URL=https://your-render-backend-url`

After both frontend deployments are live, update the Render backend environment variables:

- `FRONTEND_USER_URL=https://your-user-frontend-url`
- `SITE_BASE_URL=https://your-render-backend-url`
- `ALIPAY_NOTIFY_URL=https://your-render-backend-url/api/pay/alipay/notify`
- `ALIPAY_RETURN_URL=https://your-user-frontend-url`
