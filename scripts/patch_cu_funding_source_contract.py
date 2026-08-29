from pathlib import Path


path = Path("src/rate_monitor/collectors/cu/funding.py")
text = path.read_text(encoding="utf-8")
changed = False

old_year = '_YEAR = re.compile(r"(20\\d{2})\\s*년(?:도)?")'
new_year = '_YEAR = re.compile(r"^\\s*(20\\d{2})(?:\\s*년(?:도)?|\\s*회계연도)?")'
if old_year in text:
    text = text.replace(old_year, new_year, 1)
    changed = True
elif new_year not in text:
    raise SystemExit("CU year regex가 expected old/new 어느 쪽도 아니다")

old = '''    prior_disclosure_no: int | None = None

    for page in range(1, MAX_LIST_PAGES + 1):
'''
new = '''    declared_total: int | None = None

    for page in range(1, MAX_LIST_PAGES + 1):
'''
if old in text:
    text = text.replace(old, new, 1)
    changed = True
elif new not in text:
    raise SystemExit("CU pagination prelude가 expected old/new 어느 쪽도 아니다")

old = '''        for row in rows:
            returned = str(row.get("cuIngno") or "").strip()
            if returned != cu_ingno:
                raise CuFundingContractError(
                    "신협 공시목록 identity 불일치: "
                    f"requested={cu_ingno} returned={returned!r}"
                )
            raw_no = str(row.get("disclosureNo") or "").strip()
            if raw_no.isdigit():
                disclosure_no = int(raw_no)
                if prior_disclosure_no is not None and disclosure_no > prior_disclosure_no:
                    raise CuFundingContractError(
                        "신협 공시목록 최신순 계약 불일치: "
                        f"previous={prior_disclosure_no} current={disclosure_no}"
                    )
                prior_disclosure_no = disclosure_no
'''
new = '''        for row in rows:
            returned = str(row.get("cuIngno") or "").strip()
            if returned != cu_ingno:
                raise CuFundingContractError(
                    "신협 공시목록 identity 불일치: "
                    f"requested={cu_ingno} returned={returned!r}"
                )

        page_totals = {
            int(str(row.get("listTotalCount")))
            for row in rows
            if str(row.get("listTotalCount") or "").isdigit()
        }
        if len(page_totals) > 1:
            raise CuFundingContractError(
                f"신협 공시목록 totalCount가 한 페이지 안에서 다르다: {sorted(page_totals)}"
            )
        if page_totals:
            page_total = next(iter(page_totals))
            if declared_total is None:
                declared_total = page_total
            elif declared_total != page_total:
                raise CuFundingContractError(
                    "신협 공시목록 totalCount가 페이지 사이에서 바뀌었다: "
                    f"expected={declared_total} actual={page_total}"
                )
'''
if old in text:
    text = text.replace(old, new, 1)
    changed = True
elif new not in text:
    raise SystemExit("CU monotonic block가 expected old/new 어느 쪽도 아니다")

old = '''        all_rows.extend(rows)

        selected = select_latest_disclosures(
            all_rows,
            cu_ingno=cu_ingno,
            periods=periods,
        )
        totals = {
            int(str(row.get("listTotalCount")))
            for row in rows
            if str(row.get("listTotalCount") or "").isdigit()
        }
        total = max(totals) if totals else None
        if len(selected) >= periods:
            break
        if not rows or (total is not None and page * LIST_PAGE_SIZE >= total):
            break
        if request_interval:
            time.sleep(request_interval)
    else:
        raise CuFundingContractError(
            f"신협 공시목록 pagination이 {MAX_LIST_PAGES} page를 초과했다: {cu_ingno}"
        )
    return all_rows, artifacts
'''
new = '''        all_rows.extend(rows)
        if declared_total is not None:
            if len(all_rows) > declared_total:
                raise CuFundingContractError(
                    "신협 공시목록 row 수가 declared total을 초과했다: "
                    f"rows={len(all_rows)} total={declared_total}"
                )
            if len(all_rows) == declared_total:
                break
        if not rows:
            break
        if declared_total is None and len(rows) < LIST_PAGE_SIZE:
            break
        if request_interval:
            time.sleep(request_interval)
    else:
        raise CuFundingContractError(
            f"신협 공시목록 pagination이 {MAX_LIST_PAGES} page를 초과했다: {cu_ingno}"
        )

    if declared_total is not None and len(all_rows) != declared_total:
        raise CuFundingContractError(
            "신협 공시목록 pagination 미완료: "
            f"rows={len(all_rows)} total={declared_total} cuIngno={cu_ingno}"
        )
    return all_rows, artifacts
'''
if old in text:
    text = text.replace(old, new, 1)
    changed = True
elif new not in text:
    raise SystemExit("CU early-break block가 expected old/new 어느 쪽도 아니다")

if changed:
    path.write_text(text, encoding="utf-8")
    print("CU source-contract patch applied")
else:
    print("CU source-contract patch already applied")
