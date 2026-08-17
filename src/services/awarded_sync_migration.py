"""Awarded Sync Migration (AWARDED-SYNC-1).

1. Выгружает подрядчиков из reestr_contract_44_fz_awarded / reestr_contract_223_fz_awarded.
2. Синхронизирует contractor_id -> winner_name/winner_inn в crm_procurements.
3. Обеспечивает защиту ручных полей от затирания NULL-значениями.
"""
from __future__ import annotations

import logging
import sys
import json
from dotenv import load_dotenv

logger = logging.getLogger("awarded_sync")

def run_sync(tender_db, crm_db) -> dict:
    logger.info("Запуск оптимизированной синхронизации AWARDED-SYNC-1...")
    
    # 1. Загружаем все закупки из CRM в память
    crm_rows = crm_db.execute_query(
        "SELECT id, contract_number, winner_name, winner_inn FROM crm_procurements WHERE contract_number IS NOT NULL AND contract_number <> ''"
    ) or []
    crm_dict = {}
    for row in crm_rows:
        cn = row.get("contract_number")
        if cn:
            crm_dict[cn] = row
            
    logger.info(f"Загружено {len(crm_dict)} активных номеров контрактов из CRM")
    if not crm_dict:
        return {"updated": 0, "skipped": 0, "unchanged": 0}
        
    # 2. Выгружаем всех подрядчиков из 44-ФЗ Awarded
    query_44 = """
        SELECT 
            r.contract_number,
            COALESCE(c.short_name, c.full_name) as contractor_name,
            c.inn as contractor_inn
        FROM reestr_contract_44_fz_awarded r
        LEFT JOIN contractor c ON c.id = r.contractor_id
        WHERE r.contractor_id IS NOT NULL AND r.contract_number IS NOT NULL AND r.contract_number <> ''
    """
    rows_44 = tender_db.execute_query(query_44) or []
    logger.info(f"Найдено {len(rows_44)} записей подрядчиков в reestr_contract_44_fz_awarded")
    
    # 3. Выгружаем всех подрядчиков из 223-ФЗ Awarded
    query_223 = """
        SELECT 
            r.contract_number,
            COALESCE(c.short_name, c.full_name) as contractor_name,
            c.inn as contractor_inn
        FROM reestr_contract_223_fz_awarded r
        LEFT JOIN contractor c ON c.id = r.contractor_id
        WHERE r.contractor_id IS NOT NULL AND r.contract_number IS NOT NULL AND r.contract_number <> ''
    """
    rows_223 = tender_db.execute_query(query_223) or []
    logger.info(f"Найдено {len(rows_223)} записей подрядчиков в reestr_contract_223_fz_awarded")
    
    all_rows = []
    # Собираем данные
    for row in rows_44 + rows_223:
        if isinstance(row, dict):
            all_rows.append(row)
        else:
            all_rows.append({
                "contract_number": row[0],
                "contractor_name": row[1],
                "contractor_inn": row[2]
            })
            
    updated = skipped = unchanged = 0
    update_params = []
    
    # 4. Проводим сопоставление в памяти
    for r in all_rows:
        cn = r["contract_number"]
        name = r["contractor_name"]
        inn = r["contractor_inn"]
        
        if cn not in crm_dict:
            skipped += 1
            continue
            
        crm_rec = crm_dict[cn]
        
        # Проверяем, заполнены ли уже данные
        cur_winner_name = crm_rec.get("winner_name")
        cur_winner_inn = crm_rec.get("winner_inn")
        
        # Если ИНН и Имя уже заполнены, пропускаем
        if cur_winner_inn and cur_winner_name:
            unchanged += 1
            continue
            
        # Обновляем поля
        update_params.append((name, inn, name, inn, cn))
        updated += 1
        
    if update_params:
        logger.info(f"Отправка батч-обновления для {len(update_params)} записей в CRM...")
        crm_db.execute_many(
            """
            UPDATE crm_procurements SET
                winner_name = COALESCE(winner_name, %s),
                winner_inn = COALESCE(winner_inn, %s),
                contractor_name = COALESCE(contractor_name, %s),
                contractor_inn = COALESCE(contractor_inn, %s),
                crm_updated_at = NOW()
            WHERE contract_number = %s
            """,
            update_params
        )
        
    logger.info(f"Синхронизация AWARDED-SYNC-1 завершена. Обновлено={updated}, пропущено={skipped}, не требовалось изменений={unchanged}")
    return {
        "updated": updated,
        "skipped": skipped,
        "unchanged": unchanged
    }

def main():
    sys.path.insert(0, "/opt/CRM_Streamlit")
    sys.path.insert(0, "/opt/pythonProject89")
    load_dotenv("/opt/CRM_Streamlit/.env")
    
    from src.services.db_bootstrap import connect_databases
    _r, tender_db, crm_db, warn = connect_databases()
    if warn:
        logger.warning(f"Connection warning: {warn}")
        
    result = run_sync(tender_db, crm_db)
    print(json.dumps(result))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    main()
