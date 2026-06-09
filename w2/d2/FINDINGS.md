# W2-D2 Findings

## Cluster chinh

Cluster chinh la `c-001-000`, va root cause ma em xac dinh la `payment-svc`. Ly do chinh la hai lop score deu cung huong. Ve topology, `payment-svc` nam o vi tri cuoi cua call chain `edge-lb -> checkout-svc -> payment-svc`, nen khi co su co o payment thi checkout va edge-lb alert theo la hop ly. Ve thoi gian, cac alert lien quan den pool va latency cua `payment-svc` xuat hien som nhat trong cluster, trong khi cac alert cua `checkout-svc` va `edge-lb` den sau. Sau khi combine `0.6 * pagerank + 0.4 * timestamp`, `payment-svc` dung top-1 voi confidence `0.98`. Retrieval cung lay dung `INC-2025-11-08` lam incident giong nhat, va incident nay co class `connection_pool_exhaustion`, rat sat voi fingerprint `db_connection_pool_used_ratio` cua cluster hien tai. Trong `graph_top3`, `cart-svc` dung #3 voi score `0.58`. Dieu nay van hop ly vi `cart-svc` nam trong cluster `c-001-000` va cung bi anh huong boi checkout path, nhung no la victim yeu hon so voi `checkout-svc` va `edge-lb`, nen em khong xem no la candidate root cause manh.

## Co dam auto-remediation khong

Neu chi nhin vao cluster chinh, em co the chap nhan mot nguong auto-remediation kha cao, khoang `0.90`. Ly do la cluster nay co ba dau hieu cung luc: root cause service hop ly tren graph, timestamp den som, va retrieval match vao mot incident lich su rat sat. Tuy nhien, em khong muon bat auto-remediation chi dua vao confidence thuan tuy. Trong output cua em, cac cluster singleton nhu `notification-svc`, `recommender-svc`, va `search-svc` deu co confidence `1.0` chi vi graph cua chung chi co mot node. Nhu vay confidence cao khong dong nghia voi ket luan manh. Neu ap dung production, em se them dieu kien bo sung: chi cho auto-remediation khi confidence >= `0.90`, class nam trong mot allowlist an toan, va retrieval top-1 co root cause class phu hop voi fingerprint cua cluster.

## Case em khong chac

Case em khong chac nhat la `c-001-001` cua `notification-svc`. Graph RCA cho ra `notification-svc` la top-1 vi cluster chi co mot service, nen confidence thanh `1.0`. Sau khi classifier doc retrieval top-1 `INC-2026-02-08`, cluster nay duoc gan class `downstream_provider`, nghia la ve mat nhan incident thi pipeline da hop ly hon. Tuy nhien y nghia van hanh van chua that su manh, vi notification trong GeekShop la async path. Queue backlog co the do outage cua downstream provider, nhung cung co the chi la he qua cua mot incident lon hon ma cluster hien tai khong nhin thay. Vi vay em van xem singleton cluster nay la mot canh bao can review thu cong, khong phai mot RCA du de auto-act.

## Bonus path

Em khong chon bonus trong bai nay. Ly do la retrieval-only da du dung cho dataset hien tai: cluster chinh da lay dung `INC-2025-11-08`, class tra ve hop ly, va action cung sat voi pattern pool exhaustion. Them TF-IDF co the cai thien ranking o mot vai cluster singleton, nhung voi khung nop bai va muc tieu pass acceptance an toan, em uu tien mot pipeline don gian, de debug, va co fallback ro rang hon la them mot layer so sanh nua.
