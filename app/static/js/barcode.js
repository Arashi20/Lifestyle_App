// Reads a barcode via the device camera, then hands off to the server
// (/scanner/result/<barcode>) for the lookup, display, and save flow.

const resultBox = document.getElementById("scan-result");

function onScanSuccess(decodedText) {
    html5QrcodeScanner.clear();
    resultBox.innerHTML = `<p>Scanned: ${decodedText}. Looking up...</p>`;
    window.location.href = `/scanner/result/${encodeURIComponent(decodedText)}`;
}

// A wide, short box fits a 1D product barcode (EAN/UPC) much better than a
// square one — a square box forces the whole barcode width into a shorter
// span, making it harder for the decoder to lock on. Requesting a higher
// resolution stream also helps: browsers often default a webcam to ~640x480,
// which is too coarse to resolve a barcode's thin bars up close.
const html5QrcodeScanner = new Html5QrcodeScanner("reader", {
    fps: 10,
    qrbox: { width: 300, height: 120 },
    videoConstraints: { width: { ideal: 1280 }, height: { ideal: 720 } },
});
html5QrcodeScanner.render(onScanSuccess);
