"""Shopify Admin REST actions (products, customers, tags, orders)."""
from __future__ import annotations

from typing import Any

import httpx

from .tags_util import normalize_tags

def _shopify_tags_str(tags) -> str:
    """Shopify-facing tags (comma+space)."""
    raw = normalize_tags(tags)
    return ", ".join(raw.split(",")) if raw else ""

def _shopify_base(secrets: dict, meta: dict) -> tuple[str | None, str | None, str]:
    shop = (meta.get("shop_domain") or secrets.get("shop_domain") or "").strip()
    shop = shop.replace("https://", "").replace("http://", "").strip("/").split("/")[0]
    token = secrets.get("access_token") or secrets.get("admin_api_token") or ""
    ver = secrets.get("api_version") or meta.get("api_version") or "2024-10"
    if not shop or not token:
        return None, None, ver
    return shop, token, ver


async def shopify_action(action, secrets, meta, payload):
    """Shopify Admin REST - products/customers with tags, orders, fulfillments."""
    payload = payload or {}
    shop, token, ver = _shopify_base(secrets, meta)
    if not shop or not token:
        return {"ok": False, "error": "Shopify shop_domain + access_token required"}
    base = f"https://{shop}/admin/api/{ver}"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    action = (action or "status").lower().replace("-", "_")

    async with httpx.AsyncClient(timeout=40) as client:
        # -- Shop health ------------------------------------------
        if action in ("status", "test", "shop"):
            r = await client.get(f"{base}/shop.json", headers=headers)
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:300]}
            data = r.json()
            return {
                "ok": True,
                "message": f"Shopify connected · {(data.get('shop') or {}).get('name') or shop}",
                "data": data,
                "shop_domain": shop,
            }

        # -- List / get products (includes tags) -------------------
        if action in ("products", "get_products", "list_products"):
            limit = min(int(payload.get("limit") or 50), 250)
            params = {"limit": limit}
            if payload.get("ids"):
                params["ids"] = payload["ids"]
            if payload.get("product_id") or payload.get("id"):
                pid = payload.get("product_id") or payload.get("id")
                r = await client.get(f"{base}/products/{pid}.json", headers=headers)
            else:
                if payload.get("title"):
                    params["title"] = payload["title"]
                if payload.get("vendor"):
                    params["vendor"] = payload["vendor"]
                # Shopify product list doesn't filter by tag in REST well - client-side filter later
                r = await client.get(f"{base}/products.json", headers=headers, params=params)
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:400]}
            data = r.json()
            products = data.get("products") or ([data["product"]] if data.get("product") else [])
            tag_filter = (payload.get("tag") or payload.get("tags") or "").strip().lower()
            simplified = []
            for p in products:
                tags = _shopify_tags_str(p.get("tags") or "")
                if tag_filter and tag_filter not in tags.lower():
                    continue
                variants = p.get("variants") or []
                price = variants[0].get("price") if variants else "0"
                sku = variants[0].get("sku") if variants else ""
                simplified.append({
                    "id": p.get("id"),
                    "title": p.get("title"),
                    "handle": p.get("handle"),
                    "status": p.get("status"),
                    "vendor": p.get("vendor"),
                    "product_type": p.get("product_type"),
                    "tags": tags,
                    "tags_list": [t.strip() for t in tags.split(",") if t.strip()],
                    "sku": sku,
                    "price": price,
                    "body_html": (p.get("body_html") or "")[:2000],
                    "image": ((p.get("image") or {}).get("src") if p.get("image") else None)
                    or ((p.get("images") or [{}])[0].get("src") if p.get("images") else None),
                    "variants_count": len(variants),
                })
            return {
                "ok": True,
                "message": f"{len(simplified)} Shopify product(s)",
                "data": {"products": simplified, "count": len(simplified), "shop_domain": shop},
            }

        # -- Create / update product (title, price, tags, body) ----
        if action in ("update_product", "create_product", "product_update"):
            pid = payload.get("product_id") or payload.get("id")
            product_body: dict[str, Any] = {}
            if payload.get("title"):
                product_body["title"] = str(payload["title"]).strip()
            if payload.get("body_html") is not None or payload.get("description") is not None:
                product_body["body_html"] = payload.get("body_html") or payload.get("description") or ""
            if payload.get("vendor"):
                product_body["vendor"] = str(payload["vendor"]).strip()
            if payload.get("product_type") or payload.get("kind"):
                product_body["product_type"] = str(payload.get("product_type") or payload.get("kind") or "").strip()
            if payload.get("status"):
                product_body["status"] = str(payload["status"]).strip()
            if "tags" in payload or payload.get("tags") is not None:
                product_body["tags"] = _shopify_tags_str(payload.get("tags"))
            # Append tags without wiping existing
            if payload.get("add_tags") and pid:
                gr = await client.get(f"{base}/products/{pid}.json", headers=headers)
                if gr.status_code < 400:
                    existing = (gr.json().get("product") or {}).get("tags") or ""
                    merged = _shopify_tags_str(
                        f"{existing}, {_shopify_tags_str(payload.get('add_tags'))}"
                    )
                    product_body["tags"] = merged
            if payload.get("price") is not None and pid:
                # Update first variant price
                gr = await client.get(f"{base}/products/{pid}.json", headers=headers)
                if gr.status_code < 400:
                    prod = gr.json().get("product") or {}
                    variants = prod.get("variants") or []
                    if variants:
                        vid = variants[0]["id"]
                        vr = await client.put(
                            f"{base}/variants/{vid}.json",
                            headers=headers,
                            json={"variant": {"id": vid, "price": str(payload["price"])}},
                        )
                        if vr.status_code >= 400:
                            return {"ok": False, "error": f"Variant price: {vr.text[:300]}"}
            if payload.get("inventory") is not None and pid:
                # Inventory requires inventory_item_id + location - skip complex path; note only
                product_body.setdefault("tags", product_body.get("tags"))  # no-op keep
            if not product_body and not pid:
                return {"ok": False, "error": "Provide title (create) or product_id + fields (update)"}
            if pid:
                product_body["id"] = int(pid)
                r = await client.put(
                    f"{base}/products/{pid}.json",
                    headers=headers,
                    json={"product": product_body},
                )
            else:
                if "title" not in product_body:
                    return {"ok": False, "error": "title required to create product"}
                if payload.get("price") is not None:
                    product_body["variants"] = [{"price": str(payload["price"])}]
                r = await client.post(
                    f"{base}/products.json",
                    headers=headers,
                    json={"product": product_body},
                )
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:400]}
            p = (r.json() or {}).get("product") or {}
            return {
                "ok": True,
                "message": f"Shopify product {'updated' if pid else 'created'}: {p.get('title')}",
                "data": {
                    "id": p.get("id"),
                    "title": p.get("title"),
                    "tags": p.get("tags") or "",
                    "tags_list": [t.strip() for t in (p.get("tags") or "").split(",") if t.strip()],
                    "status": p.get("status"),
                },
            }

        # -- Customers (includes tags) -----------------------------
        if action in ("customers", "get_customers", "list_customers"):
            limit = min(int(payload.get("limit") or 50), 250)
            params: dict[str, Any] = {"limit": limit}
            q = (payload.get("query") or payload.get("q") or payload.get("email") or "").strip()
            if payload.get("customer_id") or payload.get("id"):
                cid = payload.get("customer_id") or payload.get("id")
                r = await client.get(f"{base}/customers/{cid}.json", headers=headers)
            elif q:
                r = await client.get(
                    f"{base}/customers/search.json",
                    headers=headers,
                    params={"query": q, "limit": limit},
                )
            else:
                r = await client.get(f"{base}/customers.json", headers=headers, params=params)
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:400]}
            data = r.json()
            customers = data.get("customers") or ([data["customer"]] if data.get("customer") else [])
            tag_filter = (payload.get("tag") or "").strip().lower()
            simplified = []
            for c in customers:
                tags = _shopify_tags_str(c.get("tags") or "")
                if tag_filter and tag_filter not in tags.lower():
                    continue
                simplified.append({
                    "id": c.get("id"),
                    "email": c.get("email") or "",
                    "first_name": c.get("first_name") or "",
                    "last_name": c.get("last_name") or "",
                    "name": f"{c.get('first_name') or ''} {c.get('last_name') or ''}".strip() or (c.get("email") or "Customer"),
                    "phone": c.get("phone") or "",
                    "tags": tags,
                    "tags_list": [t.strip() for t in tags.split(",") if t.strip()],
                    "orders_count": c.get("orders_count"),
                    "total_spent": c.get("total_spent"),
                    "note": c.get("note") or "",
                    "accepts_marketing": c.get("accepts_marketing"),
                })
            return {
                "ok": True,
                "message": f"{len(simplified)} Shopify customer(s)",
                "data": {"customers": simplified, "count": len(simplified), "shop_domain": shop},
            }

        # -- Update customer tags / fields -------------------------
        if action in ("update_customer", "customer_update", "update_customer_tags"):
            cid = payload.get("customer_id") or payload.get("id")
            if not cid:
                return {"ok": False, "error": "customer_id required"}
            body: dict[str, Any] = {"id": int(cid)}
            if payload.get("email"):
                body["email"] = str(payload["email"]).strip()
            if payload.get("first_name"):
                body["first_name"] = str(payload["first_name"]).strip()
            if payload.get("last_name"):
                body["last_name"] = str(payload["last_name"]).strip()
            if payload.get("phone"):
                body["phone"] = str(payload["phone"]).strip()
            if payload.get("note") is not None:
                body["note"] = str(payload.get("note") or "")
            if "tags" in payload or payload.get("tags") is not None:
                body["tags"] = _shopify_tags_str(payload.get("tags"))
            if payload.get("add_tags"):
                gr = await client.get(f"{base}/customers/{cid}.json", headers=headers)
                if gr.status_code < 400:
                    existing = (gr.json().get("customer") or {}).get("tags") or ""
                    body["tags"] = _shopify_tags_str(
                        f"{existing}, {_shopify_tags_str(payload.get('add_tags'))}"
                    )
            r = await client.put(
                f"{base}/customers/{cid}.json",
                headers=headers,
                json={"customer": body},
            )
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:400]}
            c = (r.json() or {}).get("customer") or {}
            return {
                "ok": True,
                "message": f"Shopify customer updated · tags: {c.get('tags') or '-'}",
                "data": {
                    "id": c.get("id"),
                    "email": c.get("email"),
                    "tags": c.get("tags") or "",
                    "tags_list": [t.strip() for t in (c.get("tags") or "").split(",") if t.strip()],
                },
            }

        # -- Orders ------------------------------------------------
        if action in ("orders", "get_orders", "list_orders"):
            limit = min(int(payload.get("limit") or 25), 250)
            params = {"limit": limit, "status": payload.get("status") or "any"}
            if payload.get("customer_email") or payload.get("email"):
                # Search by email via query param on orders if supported - use customer search fallback
                email = payload.get("customer_email") or payload.get("email")
                params["email"] = email
            r = await client.get(f"{base}/orders.json", headers=headers, params=params)
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:400]}
            orders = (r.json() or {}).get("orders") or []
            simplified = []
            for o in orders:
                simplified.append({
                    "id": o.get("id"),
                    "name": o.get("name"),
                    "email": o.get("email"),
                    "financial_status": o.get("financial_status"),
                    "fulfillment_status": o.get("fulfillment_status"),
                    "total_price": o.get("total_price"),
                    "currency": o.get("currency"),
                    "tags": o.get("tags") or "",
                    "created_at": o.get("created_at"),
                    "customer_id": (o.get("customer") or {}).get("id"),
                })
            return {
                "ok": True,
                "message": f"{len(simplified)} order(s)",
                "data": {"orders": simplified, "count": len(simplified)},
            }

        # -- Order note --------------------------------------------
        if action in ("create_order_note", "order_note", "add_order_note"):
            oid = payload.get("order_id") or payload.get("id")
            note = (payload.get("note") or payload.get("message") or "").strip()
            if not oid or not note:
                return {"ok": False, "error": "order_id and note required"}
            gr = await client.get(f"{base}/orders/{oid}.json", headers=headers)
            if gr.status_code >= 400:
                return {"ok": False, "error": gr.text[:300]}
            existing = (gr.json().get("order") or {}).get("note") or ""
            new_note = f"{existing}\n{note}".strip() if existing else note
            r = await client.put(
                f"{base}/orders/{oid}.json",
                headers=headers,
                json={"order": {"id": int(oid), "note": new_note}},
            )
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:400]}
            return {"ok": True, "message": "Order note saved", "data": {"order_id": oid, "note": new_note}}

        # -- Fulfill order (simple full fulfillment) ---------------
        if action in ("fulfill_order", "fulfill"):
            oid = payload.get("order_id") or payload.get("id")
            if not oid:
                return {"ok": False, "error": "order_id required"}
            # Get fulfillment orders (2023+ API)
            fo = await client.get(f"{base}/orders/{oid}/fulfillment_orders.json", headers=headers)
            if fo.status_code >= 400:
                # Fallback legacy fulfillments
                body = {
                    "fulfillment": {
                        "location_id": payload.get("location_id"),
                        "tracking_number": payload.get("tracking_number") or None,
                        "tracking_urls": [payload["tracking_url"]] if payload.get("tracking_url") else None,
                        "notify_customer": bool(payload.get("notify_customer", True)),
                    }
                }
                # Need line items from order
                orr = await client.get(f"{base}/orders/{oid}.json", headers=headers)
                if orr.status_code >= 400:
                    return {"ok": False, "error": orr.text[:300]}
                line_items = [
                    {"id": li["id"]}
                    for li in (orr.json().get("order") or {}).get("line_items") or []
                ]
                body["fulfillment"]["line_items"] = line_items
                r = await client.post(f"{base}/orders/{oid}/fulfillments.json", headers=headers, json=body)
                if r.status_code >= 400:
                    return {"ok": False, "error": r.text[:400]}
                return {"ok": True, "message": "Order fulfilled", "data": r.json()}
            fulfillment_orders = (fo.json() or {}).get("fulfillment_orders") or []
            open_fos = [
                f for f in fulfillment_orders
                if (f.get("status") or "") in ("open", "in_progress", "scheduled")
            ]
            if not open_fos:
                return {"ok": False, "error": "No open fulfillment orders for this order"}
            results = []
            for fobj in open_fos:
                fid = fobj["id"]
                line_items = [
                    {"id": li["id"], "quantity": li.get("quantity") or li.get("fulfillable_quantity") or 1}
                    for li in (fobj.get("line_items") or [])
                    if (li.get("fulfillable_quantity") or 0) > 0 or li.get("quantity")
                ]
                fbody = {
                    "fulfillment": {
                        "line_items_by_fulfillment_order": [{
                            "fulfillment_order_id": fid,
                            "fulfillment_order_line_items": line_items or None,
                        }],
                        "notify_customer": bool(payload.get("notify_customer", True)),
                    }
                }
                if payload.get("tracking_number"):
                    fbody["fulfillment"]["tracking_info"] = {
                        "number": payload.get("tracking_number"),
                        "url": payload.get("tracking_url") or "",
                    }
                # Clean None line items
                if not line_items:
                    fbody["fulfillment"]["line_items_by_fulfillment_order"] = [
                        {"fulfillment_order_id": fid}
                    ]
                r = await client.post(f"{base}/fulfillments.json", headers=headers, json=fbody)
                results.append({"status": r.status_code, "body": r.json() if r.status_code < 400 else r.text[:200]})
            ok = any(x["status"] < 400 for x in results)
            return {
                "ok": ok,
                "message": "Fulfillment submitted" if ok else "Fulfillment failed",
                "data": {"results": results, "order_id": oid},
            }

        # Unknown action - try generic GET map for back-compat
        path = {
            "orders": "/orders.json?limit=5&status=any",
            "products": "/products.json?limit=5",
            "customers": "/customers.json?limit=5",
        }.get(action)
        if path:
            r = await client.get(base + path, headers=headers)
            if r.status_code >= 400:
                return {"ok": False, "error": r.text[:300]}
            return {"ok": True, "message": f"Shopify {action}", "data": r.json()}

        return {
            "ok": False,
            "error": (
                f"Unknown Shopify action '{action}'. "
                "Use: products, customers, update_product, update_customer, "
                "get_orders, create_order_note, fulfill_order, status"
            ),
        }


