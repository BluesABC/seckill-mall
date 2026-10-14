"""Exercise public catalog pagination against the owned S7 WSL stack."""
import json
from urllib.parse import urlencode
from stack_client import ROOT, PROJECT, call, clean, sql

assert PROJECT == "seckill-mall-s7"
prefix = "S9CAT" + __import__("secrets").token_hex(6)
categories = ("跑步", "篮球", "休闲", "训练")
try:
    rows = ",".join(
        f"('{prefix}_{i:03d}','S9 isolated pagination fixture','/assets/shoe-run-v1.png')"
        for i in range(105)
    )
    sql("INSERT INTO goods(title,description,image_url) VALUES" + rows)
    ids = [int(value) for value in sql(
        f"SELECT id FROM goods WHERE title LIKE '{prefix}_%' ORDER BY id DESC"
    ).splitlines()]
    sku_rows = ",".join(
        f"({goods_id},{10000+(i%11)*1000},1,'42',CONVERT(UNHEX('{categories[i%4].encode().hex()}') USING utf8mb4),CONVERT(UNHEX('{('黑 / 白').encode().hex()}') USING utf8mb4))"
        for i, goods_id in enumerate(ids)
    )
    sql("INSERT INTO skus(goods_id,price_fen,unallocated_stock,size_eu,category,colorway) VALUES" + sku_rows)

    seen = []
    pages = []
    for page in range(5):
        query = urlencode({"q": prefix, "page": page, "size": 24})
        code, result = call("GET", "/api/goods/catalog?" + query)
        assert code == 200, result
        assert (result["page"], result["size"], result["total"], result["hasMore"]) == (page, 24, 105, page < 4), result
        pages.append(len(result["items"]))
        seen.extend(item["goodsId"] for item in result["items"])
    assert pages == [24, 24, 24, 24, 9], pages
    assert len(seen) == len(set(seen)) == 105

    filters = {"q": prefix, "category": "跑步", "maxPriceFen": 50000, "sort": "low", "size": 48}
    for subset in ({"category": "跑步"}, {"q": prefix, "category": "跑步"}, {"q": prefix, "maxPriceFen": 50000},
                   {"q": prefix, "sort": "low"}, {"q": prefix, "size": 48}, filters):
        code, filtered = call("GET", "/api/goods/catalog?" + urlencode(subset))
        assert code == 200, (subset, filtered)
        assert filtered["total"] > 0, (subset, filtered)
    prices = [int(item["priceFen"]) for item in filtered["items"]]
    assert prices == sorted(prices), prices
    assert all(item["category"] == "跑步" and int(item["priceFen"]) <= 50000 for item in filtered["items"])
    code, no_matches = call("GET", "/api/goods/catalog?" + urlencode({"q": "不存在"}))
    assert code == 200 and no_matches["total"] == 0, no_matches
    for invalid in ("page=-1", "size=49", "sort=arbitrary", "maxPriceFen=0", "unknown=x", "%71=encoded-key"):
        assert call("GET", "/api/goods/catalog?" + invalid)[0] == 400, invalid
    assert len(call("GET", "/api/goods")[1]["items"]) <= 100
    assert clean()["status"] == "CLEAN"
    report = {"platform": "WSL2 Ubuntu", "project": PROJECT, "products": 105,
              "pageSize": 24, "pageSizes": pages, "duplicateGoodsAcrossPages": False,
              "filtersAndPriceSort": "PASS", "invalidInputs": 6, "status": "PASS"}
    target = ROOT / "tests/reports/wsl/s9-catalog-api.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("PASS S9 catalog API", json.dumps(report, ensure_ascii=False), flush=True)
finally:
    sql(f"DELETE s FROM skus s JOIN goods g ON g.id=s.goods_id WHERE g.title LIKE '{prefix}_%'")
    sql(f"DELETE FROM goods WHERE title LIKE '{prefix}_%'")
    assert clean()["status"] == "CLEAN"
