/**
 * CHRONOS WhatsApp Web Bridge (Node.js)
 *
 * Requires: npm install whatsapp-web.js express qrcode cors
 *
 * Run: node wa-bridge.js
 * Then open http://localhost:3000/qr to scan the QR code with your phone.
 * Once authenticated, the Flask backend can POST to /send to deliver files.
 */

const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const express = require('express');
const qrcode = require('qrcode');
const cors = require('cors');
const fs = require('fs');

const client = new Client({
  authStrategy: new LocalAuth({ dataPath: './wa-session' }),
  puppeteer: { headless: true, args: ['--no-sandbox'] }
});

const app = express();
app.use(cors());
app.use(express.json({ limit: '50mb' }));

let qrCodeData = null;
let ready = false;

client.on('qr', async (qr) => {
  qrCodeData = await qrcode.toDataURL(qr);
  console.log('[WA-BRIDGE] QR generated. Open http://localhost:3000/qr to scan.');
});

client.on('ready', () => {
  ready = true;
  qrCodeData = null;
  console.log('[WA-BRIDGE] Authenticated and ready for outgoing messages.');
});

client.on('auth_failure', (msg) => {
  console.log('[WA-BRIDGE] Auth failure:', msg);
  ready = false;
});

client.on('disconnected', (reason) => {
  console.log('[WA-BRIDGE] Disconnected:', reason);
  ready = false;
});

app.get('/qr', async (req, res) => {
  if (qrCodeData) {
    const base64 = qrCodeData.split(',')[1];
    const img = Buffer.from(base64, 'base64');
    res.writeHead(200, { 'Content-Type': 'image/png', 'Content-Length': img.length });
    res.end(img);
  } else if (ready) {
    res.send('Already authenticated');
  } else {
    res.status(503).send('Not ready yet');
  }
});

app.get('/status', (req, res) => {
  res.json({ ready, qr: !!qrCodeData });
});

app.post('/send', async (req, res) => {
  if (!ready) return res.status(503).json({ error: 'Not authenticated' });
  const { to, file } = req.body;
  if (!to || !file) return res.status(400).json({ error: 'Missing to or file' });
  try {
    if (!fs.existsSync(file)) return res.status(400).json({ error: 'File not found' });
    const media = MessageMedia.fromFilePath(file);
    const chatId = to.includes('@') ? to : `${to}@c.us`;
    await client.sendMessage(chatId, media, { sendMediaAsDocument: true });
    res.json({ success: true });
  } catch (e) {
    console.error('[WA-BRIDGE] Send error:', e.message);
    res.status(500).json({ error: e.message });
  }
});

client.initialize();
app.listen(3000, () => {
  console.log('[WA-BRIDGE] Listening on http://localhost:3000');
  console.log('[WA-BRIDGE] Open http://localhost:3000/qr after startup to scan.');
});
