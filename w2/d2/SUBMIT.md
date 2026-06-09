# W2-D2 Submission

## Cau 1 - Confidence va threshold auto-rollback

Confidence top-1 trong cluster lon nhat ma em xu ly la `0.98`, ung voi `payment-svc` trong cluster `c-001-000`. Neu phai dat threshold de auto-rollback khong can SRE confirm, em se chon muc `0.90` thay vi lay thap hon. Ly do la confidence trong pipeline nay khong chi den tu graph ma con bi anh huong boi cau truc cluster. Cac cluster singleton trong output cua em deu dat `1.0`, nhung dieu do khong co nghia la chung du tin cay hon cluster chinh. Vi vay threshold khong the dua vao score duy nhat. Em se chi cho auto-rollback neu confidence >= `0.90`, class nam trong nhom co playbook ro rang nhu `connection_pool_exhaustion`, va similar incident top-1 cung match pattern gan voi cluster hien tai.

## Cau 2 - Variant classifier em chon

Em chon variant classifier theo huong `retrieval-based / kNN-style over incident history`, cu the la graph + temporal de rank culprit, sau do retrieval top-3 tren `incidents_history.json`, va lay `class` + `actions` tu top-1 similar incident. Chay thuc te tren dataset nay kha on vi cluster chinh da lay dung `INC-2025-11-08` va tra ve `connection_pool_exhaustion`. Trade-off la variant nay de giai thich, khong can API key, va fallback ro rang, nhung no cung bi gioi han boi schema lich su va quality cua retrieval. So voi free LLM hay paid LLM, cach lam nay kem linh hoat hon trong reasoning va khong suy luan duoc beyond history. Nguoc lai, no on dinh hon, de test hon, va hop voi bai nop auto-grader hon.

## Cau 3 - Pipeline nay gan product nao nhat

Pipeline em xay gan voi `Dynatrace Davis` nhat, vi no xem service graph la signal cot loi roi ket hop them timestamp de rank root cause. Sau do em bo sung retrieval tu lich su incident de gan class va action, nhung phan xep hang culprit van la topology-first. Trong domain GeekShop, em nghi huong nay hop ly vi day la he thong e-commerce co alert volume cao va service map tuong doi on dinh. Khi graph tuong doi tin cay, cach tiep can nay nhanh, deterministic, va phu hop cho incident response. Neu day la moi truong graph thay doi lien tuc hoac event-driven phuc tap hon, em moi nghieng sang huong nhu Causely hoac tang trong so cho retrieval / causal data. Con voi bai nay, graph + temporal + retrieval la mot diem can bang hop ly giua do chinh xac, do de giai thich, va rui ro implement.
