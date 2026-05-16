/* Loose Threads storefront — talks to the real shop API with relative URLs only.
   The cart and checkout actually work; when the shop is torn they fail for real,
   and the page shows the real status code instead of hiding it. */

(function () {
  "use strict";

  const badge = document.getElementById("cart-badge");
  const summary = document.getElementById("cart-summary");
  const checkoutBtn = document.getElementById("checkout-btn");
  const failRow = document.getElementById("fail-row");
  const banner = document.getElementById("mend-banner");
  const mendLink = document.getElementById("mend-link");
  const darnUrl = (document.body.dataset.darnUrl || "").replace(/\/$/, "");

  let cartId = null;
  let count = 0;
  let subtotalCents = 0;

  function dollars(cents) {
    return cents % 100 === 0 ? "$" + cents / 100 : "$" + (cents / 100).toFixed(2);
  }

  function renderCart() {
    if (count > 0) {
      badge.textContent = String(count);
      badge.hidden = false;
    } else {
      badge.hidden = true;
    }
    const noun = count === 1 ? "sock" : "socks";
    summary.innerHTML =
      count + " " + noun + ' <span class="dim">·</span> ' + dollars(subtotalCents);
  }

  function clearTorn() {
    failRow.hidden = true;
    banner.hidden = true;
  }

  async function showTorn(label) {
    failRow.textContent = label;
    failRow.hidden = false;
    // Find a live Darn incident to link to; degrade silently if there isn't one.
    try {
      const res = await fetch("/api/darn");
      if (res.ok) {
        const data = await res.json();
        if (data.incident_url) {
          mendLink.href = data.incident_url;
          banner.hidden = false;
          return;
        }
      }
    } catch (e) {
      /* no Darn reachable — the failrow already tells the honest story */
    }
    if (darnUrl) {
      mendLink.href = darnUrl;
      banner.hidden = false;
    }
  }

  async function postJSON(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return res;
  }

  async function addToCart(sockId) {
    clearTorn();
    try {
      const res = await postJSON("/api/cart", { sock_id: sockId, qty: 1, cart_id: cartId });
      if (!res.ok) {
        showTorn("POST /api/cart → " + res.status);
        return;
      }
      const cart = await res.json();
      cartId = cart.cart_id;
      count = cart.count;
      subtotalCents = cart.subtotal_cents;
      renderCart();
    } catch (e) {
      showTorn("POST /api/cart → failed");
    }
  }

  async function checkout() {
    clearTorn();
    checkoutBtn.disabled = true;
    try {
      const coRes = await postJSON("/api/checkout", { cart_id: cartId || "" });
      if (!coRes.ok) {
        await showTorn("POST /api/checkout → " + coRes.status);
        return;
      }
      const order = await coRes.json();
      const payRes = await postJSON("/api/pay", {
        order_id: order.order_id,
        amount_cents: order.total_cents,
      });
      if (!payRes.ok) {
        await showTorn("POST /api/pay → " + payRes.status);
        return;
      }
      // Paid for real.
      failRow.textContent = "paid ✓ " + dollars(order.total_cents) + " (incl. tax)";
      failRow.hidden = false;
      cartId = null;
      count = 0;
      subtotalCents = 0;
      renderCart();
    } catch (e) {
      await showTorn("POST /api/checkout → failed");
    } finally {
      checkoutBtn.disabled = false;
    }
  }

  document.querySelectorAll(".add").forEach(function (btn) {
    btn.addEventListener("click", function () {
      addToCart(btn.dataset.sock);
    });
  });
  checkoutBtn.addEventListener("click", checkout);

  renderCart();
})();
