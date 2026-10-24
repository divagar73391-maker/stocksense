(() => {
  const dataNode = document.getElementById('sales-data');
  if (!dataNode) return;
  const data = JSON.parse(dataNode.textContent);
  const barcodeInput = document.getElementById('barcodeLookup');
  const productBarcode = document.getElementById('productBarcode');
  const result = document.getElementById('scanResult');
  const video = document.getElementById('cameraVideo');
  const placeholder = document.getElementById('scanPlaceholder');
  let stream = null, detector = null, scanning = false, chart = null;
  const setBarcode = value => {
    barcodeInput.value = value;
    productBarcode.value = value;
    lookup(value);
  };
  async function lookup(value) {
    value = (value || barcodeInput.value || '').trim();
    if (!value) { result.textContent = 'Please scan or enter a barcode.'; return; }
    result.textContent = 'Searching your inventory…';
    try {
      const res = await fetch(`/scan_lookup?barcode=${encodeURIComponent(value)}`);
      const body = await res.json();
      if (!res.ok) throw new Error(body.error || 'Lookup failed.');
      if (!body.found) {
        result.innerHTML = `<strong>New barcode: ${escapeHtml(body.barcode)}</strong><br>${escapeHtml(body.message)} Add the product details in the stock form below.`;
        document.getElementById('productBarcode').value = body.barcode;
        return;
      }
      result.innerHTML = `<strong>${body.batches.length} batch(es) found for ${escapeHtml(body.barcode)}</strong>` +
        body.batches.map(b => `<div class="batch-result"><b>${escapeHtml(b.name)}</b> · ${escapeHtml(b.batch_number || 'Stock '+b.id)}<br>${b.quantity} units · expiry ${escapeHtml(b.expiry_date || 'not set')} · ${escapeHtml(b.status)}<br><button type="button" class="btn ghost choose-batch" data-id="${b.id}" data-name="${escapeAttr(b.name)}" data-barcode="${escapeAttr(body.barcode)}">Use product details</button></div>`).join('');
      result.querySelectorAll('.choose-batch').forEach(btn => btn.addEventListener('click', () => {
        const batch = body.batches.find(b => String(b.id) === btn.dataset.id);
        if (!batch) return;
        const set = (selector, value) => { const el = document.querySelector(selector); if (el && value !== null && value !== undefined) el.value = value; };
        // Autofill ONLY the six fields requested by the user.
        set('#productName', batch.name);
        set('#productBarcode', body.barcode);
        set('input[name="expiry_date"]', batch.expiry_date || '');
        set('input[name="category"]', batch.category || '');
        set('input[name="unit_cost"]', batch.unit_cost ?? 0);
        set('input[name="selling_price"]', batch.selling_price ?? 0);
        // Quantity, batch label, supplier and planning fields remain unchanged for manual entry.
        document.getElementById('scanner').scrollIntoView({behavior:'smooth'});
        const nameField = document.getElementById('productName');
        if (nameField) nameField.focus({preventScroll:true});
        result.insertAdjacentHTML('beforeend', '<p class="muted autofill-note">Product details filled into the stock form. Check the expiry date and enter the quantity for this delivery.</p>');
      }));
    } catch (e) { result.textContent = e.message; }
  }
  function escapeHtml(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
  function escapeAttr(s) { return escapeHtml(s); }
  document.getElementById('lookupBarcode')?.addEventListener('click', () => lookup());
  document.getElementById('useBarcode')?.addEventListener('click', () => {
    productBarcode.value = barcodeInput.value.trim();
    document.getElementById('scanner').scrollIntoView({behavior:'smooth'});
  });
  async function stopCamera() {
    scanning = false;
    if (stream) stream.getTracks().forEach(t => t.stop());
    stream = null; video.srcObject = null; video.style.display = 'none'; placeholder.style.display = 'flex';
  }
  document.getElementById('stopCamera')?.addEventListener('click', stopCamera);
  document.getElementById('startCamera')?.addEventListener('click', async () => {
    try {
      if (!('BarcodeDetector' in window)) { result.textContent = 'This browser does not support live barcode detection. Use manual barcode entry or upload a clear barcode photo.'; return; }
      detector = new BarcodeDetector({formats:['ean_13','ean_8','upc_a','upc_e','code_128','code_39','qr_code']});
      stream = await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'}},audio:false});
      video.srcObject = stream; video.style.display = 'block'; placeholder.style.display = 'none';
      await video.play(); scanning = true; scanFrame();
    } catch (e) { result.textContent = `Camera could not start: ${e.message}. Camera access generally requires HTTPS or localhost; use manual entry instead.`; }
  });
  async function scanFrame() {
    if (!scanning || !detector) return;
    try {
      const codes = await detector.detect(video);
      if (codes.length && codes[0].rawValue) { const code = codes[0].rawValue; await stopCamera(); setBarcode(code); return; }
    } catch (_) {}
    requestAnimationFrame(scanFrame);
  }
  document.getElementById('readImage')?.addEventListener('click', async () => {
    const file = document.getElementById('barcodeImage').files[0];
    if (!file) { result.textContent = 'Choose a barcode photo first.'; return; }
    if (!('BarcodeDetector' in window) || !('createImageBitmap' in window)) {
      result.textContent = 'This browser cannot read barcodes from uploaded photos. Enter the barcode manually or try a supported Chromium browser.';
      return;
    }
    try {
      detector = new BarcodeDetector({formats:['ean_13','ean_8','upc_a','upc_e','code_128','code_39','qr_code']});
      const bitmap = await createImageBitmap(file);
      const codes = await detector.detect(bitmap);
      bitmap.close?.();
      if (codes.length) setBarcode(codes[0].rawValue);
      else result.textContent = 'No barcode detected. Try a clearer, well-lit photo with the full barcode visible.';
    } catch(e) { result.textContent = 'Could not read this image. Please enter the barcode manually.'; }
  });
  const canvas = document.getElementById('salesChart');
  const summary = document.getElementById('chartSummary');
  function drawChart(period) {
    if (!canvas || !window.Chart) { if(summary) summary.textContent='Chart library needs internet access; use the period leader lists below.'; return; }
    const labels = data[period] || [];
    const quantities = data[period+'_qty'] || [];
    const values = data[period+'_value'] || [];
    if (chart) chart.destroy();
    chart = new Chart(canvas, {
      type:'bar',
      data:{labels, datasets:[{label:'Units sold',data:quantities,backgroundColor:'#7558e8',borderRadius:7,yAxisID:'y'}, {label:'Purchase value (₹)',data:values,backgroundColor:'#48c997',borderRadius:7,yAxisID:'y1'}]},
      options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{labels:{usePointStyle:true,boxWidth:8,font:{size:11}}}},scales:{x:{grid:{display:false},ticks:{font:{size:10}}},y:{beginAtZero:true,title:{display:true,text:'Units sold'},grid:{color:'#eef0f8'}},y1:{beginAtZero:true,position:'right',title:{display:true,text:'Purchase value (₹)'},grid:{drawOnChartArea:false}}}}
    });
    summary.textContent = `${period[0].toUpperCase()+period.slice(1)} ranking · quantity sold and estimated purchase value from recorded sales.`;
  }
  document.querySelectorAll('[data-chart]').forEach(btn => btn.addEventListener('click', () => {
    document.querySelectorAll('[data-chart]').forEach(b => b.classList.remove('active'));
    btn.classList.add('active'); drawChart(btn.dataset.chart);
  }));
  drawChart('weekly');
  document.querySelectorAll('.nav-link').forEach(link => link.addEventListener('click', () => {
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    link.classList.add('active');
  }));
})();
