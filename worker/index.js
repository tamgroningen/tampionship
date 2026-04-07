const RESEND_API_KEY = 're_TQ494wPi_2KoSCTbmTMc3qLRFMMYu2scz';

export default {
  async fetch(request, env) {
    const corsHeaders = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, PUT, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    };

    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }

    const url = new URL(request.url);
    const key = url.pathname.replace(/^\//, '') || 'default';
    const json = (data, status = 200) =>
      new Response(JSON.stringify(data), {
        status,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });

    // === OTP: Send code ===
    if (request.method === 'POST' && key === 'send-code') {
      const { email } = await request.json();
      if (!email) return json({ error: 'Email required' }, 400);

      const code = String(Math.floor(100000 + Math.random() * 900000));
      await env.TAMP_DATA.put(`otp:${email.toLowerCase()}`, code, { expirationTtl: 600 });

      const emailRes = await fetch('https://api.resend.com/emails', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${RESEND_API_KEY}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          from: 'TAMpionship <noreply@tennisiq.nl>',
          to: email,
          subject: `TAMpionship Login Code: ${code}`,
          html: `
            <div style="font-family:sans-serif;max-width:400px;margin:0 auto;text-align:center;">
              <h2 style="color:#c084fc;">TAMpionship</h2>
              <p>Je login code:</p>
              <div style="font-size:32px;font-weight:800;color:#c084fc;letter-spacing:8px;padding:16px;background:#1a1a2e;border-radius:12px;margin:16px 0;">${code}</div>
              <p style="color:#888;font-size:12px;">Deze code is 10 minuten geldig.</p>
            </div>
          `,
        }),
      });

      return emailRes.ok ? json({ ok: true }) : json({ error: 'Email send failed' }, 500);
    }

    // === OTP: Verify code ===
    if (request.method === 'POST' && key === 'verify-code') {
      const { email, code } = await request.json();
      const stored = await env.TAMP_DATA.get(`otp:${email.toLowerCase()}`);

      if (stored && stored === code) {
        await env.TAMP_DATA.delete(`otp:${email.toLowerCase()}`);
        // Log login
        const logins = JSON.parse(await env.TAMP_DATA.get('logins') || '[]');
        logins.push({ email, timestamp: new Date().toISOString() });
        await env.TAMP_DATA.put('logins', JSON.stringify(logins.slice(-1000)));
        return json({ ok: true });
      }
      return json({ ok: false, error: 'Ongeldige code' }, 401);
    }

    // === Wildcard: Get status ===
    if (request.method === 'POST' && key === 'wildcard-status') {
      const { email } = await request.json();
      if (!email) return json({ error: 'Email required' }, 400);
      const used = await env.TAMP_DATA.get(`wildcard:${email.toLowerCase()}`);
      return json({ used: !!used, data: used ? JSON.parse(used) : null });
    }

    // === Wildcard: Use wildcard (update squad) ===
    if (request.method === 'POST' && key === 'use-wildcard') {
      const { email, newSquad, oldSquad } = await request.json();
      if (!email || !newSquad) return json({ error: 'Email and newSquad required' }, 400);

      // Check not already used
      const existing = await env.TAMP_DATA.get(`wildcard:${email.toLowerCase()}`);
      if (existing) return json({ error: 'Wildcard al gebruikt' }, 400);

      // Validate squad size
      if (!Array.isArray(newSquad) || newSquad.length !== 8) {
        return json({ error: 'Squad moet 8 spelers bevatten' }, 400);
      }

      // Check no duplicates
      if (new Set(newSquad).size !== 8) {
        return json({ error: 'Elke speler mag maar 1x in je squad' }, 400);
      }

      // Store wildcard usage with old squad for point calculation
      const data = {
        email: email.toLowerCase(),
        oldSquad: oldSquad || [],
        newSquad,
        timestamp: new Date().toISOString(),
      };
      await env.TAMP_DATA.put(`wildcard:${email.toLowerCase()}`, JSON.stringify(data));

      // Also store in a list so we can apply them
      const wildcards = JSON.parse(await env.TAMP_DATA.get('wildcards') || '[]');
      wildcards.push(data);
      await env.TAMP_DATA.put('wildcards', JSON.stringify(wildcards));

      return json({ ok: true });
    }

    // === Get all wildcards (for the frontend to apply) ===
    if (request.method === 'GET' && key === 'wildcards') {
      const wildcards = JSON.parse(await env.TAMP_DATA.get('wildcards') || '[]');
      return json(wildcards);
    }

    return json({ error: 'Not found' }, 404);
  },
};
