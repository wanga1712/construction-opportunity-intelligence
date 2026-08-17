import sys
from pathlib import Path
from datetime import datetime, timedelta

# Добавляем корень проекта в sys.path, чтобы работали импорты database_work.*
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from database_work.database_connection import DatabaseManager
from database_work.daily_status_migration import (
    create_backup,
    check_and_create_status_tables,
    migrate_from_main_to_commission_work,
    migrate_from_commission_work,
)


def print_header(title: str) -> None:
    line = "=" * 60
    print(f"\n{line}\n{title}\n{line}")


def get_counts(db: DatabaseManager, table_names):
    counts = {}
    for name in table_names:
        db.cursor.execute(f"SELECT COUNT(*) FROM {name};")
        counts[name] = db.cursor.fetchone()[0]
    return counts


def force_backup_test():
    print_header("Шаг 1: Принудительный бэкап БД")
    backup_path = create_backup(force=True)
    if backup_path:
        print(f"✅ Бэкап создан: {backup_path}")
    else:
        print("⚠️ Бэкап не создан (проверьте логи)")
    return backup_path


def migration_counts_test():
    print_header("Шаг 2: Проверка миграции по таблицам (44-ФЗ и 223-ФЗ)")
    db = DatabaseManager()
    try:
        tables_44 = [
            "reestr_contract_44_fz",
            "reestr_contract_44_fz_commission_work",
            "reestr_contract_44_fz_unclear",
            "reestr_contract_44_fz_awarded",
        ]
        tables_223 = [
            "reestr_contract_223_fz",
            "reestr_contract_223_fz_commission_work",
            "reestr_contract_223_fz_unclear",
            "reestr_contract_223_fz_awarded",
        ]

        all_tables = tables_44 + tables_223

        print("→ Проверяем/создаём статусные таблицы…")
        if not check_and_create_status_tables():
            print("❌ Ошибка check_and_create_status_tables() — см. логи")
            return

        print("→ Считаем записи ДО миграции…")
        before = get_counts(db, all_tables)
        for name, cnt in before.items():
            print(f"  {name}: {cnt}")

        print("\n→ Запускаем migrate_from_main_to_commission_work('44') и '223'…")
        m44 = migrate_from_main_to_commission_work("44")
        m223 = migrate_from_main_to_commission_work("223")
        print(f"  44-ФЗ main→commission: мигрировано={m44[0]}, удалено из main={m44[1]}")
        print(f"  223-ФЗ main→commission: мигрировано={m223[0]}, удалено из main={m223[1]}")

        print("\n→ Запускаем migrate_from_commission_work('44') и '223'…")
        c44 = migrate_from_commission_work("44")
        c223 = migrate_from_commission_work("223")
        print(f"  44-ФЗ commission→unclear/awarded: {c44}")
        print(f"  223-ФЗ commission→unclear/awarded: {c223}")

        print("\n→ Считаем записи ПОСЛЕ миграции…")
        after = get_counts(db, all_tables)
        for name in all_tables:
            print(f"  {name}: {before[name]} → {after[name]} (Δ {after[name] - before[name]})")

    finally:
        db.close()


def fast_path_single_contract():
    print_header("Шаг 3: Ускоренный прогон одной тестовой закупки по статусам (44-ФЗ)")
    db = DatabaseManager()
    try:
        now = datetime.now()

        # Имя тестового контракта — чтобы легко чистить
        contract_number = f"TEST-STATUS-{now.strftime('%Y%m%d%H%M%S')}"

        print(f"→ Создаём тестовый контракт в reestr_contract_44_fz: {contract_number}")
        db.cursor.execute(
            """
            INSERT INTO reestr_contract_44_fz
                (contract_number, tender_link, auction_name,
                 start_date, end_date,
                 initial_price, customer_id, contractor_id,
                 region_id, okpd_id, trading_platform_id)
            VALUES
                (%s, %s, %s,
                 %s, %s,
                 %s, NULL, NULL,
                 NULL, NULL, NULL)
            RETURNING id;
            """,
            (
                contract_number,
                "https://test.example/contract",
                "Тестовая закупка для статусов",
                now.date(),
                (now + timedelta(days=10)).date(),  # пока не в зоне миграции
                1000.0,
            ),
        )
        contract_id = db.cursor.fetchone()[0]
        db.connection.commit()
        print(f"  ✅ Вставлен контракт id={contract_id}")

        # 1) Условие "Работа комиссии": end_date <= today+1
        print("→ Обновляем end_date, чтобы контракт попал в 'Работа комиссии'")
        db.cursor.execute(
            """
            UPDATE reestr_contract_44_fz
            SET end_date = CURRENT_DATE + INTERVAL '1 day'
            WHERE id = %s;
            """,
            (contract_id,),
        )
        db.connection.commit()

        m44 = migrate_from_main_to_commission_work("44")
        print(f"  migrate_from_main_to_commission_work('44') вернул: {m44}")

        # Проверяем, что запись ушла из основной и попала в commission_work
        db.cursor.execute(
            "SELECT COUNT(*) FROM reestr_contract_44_fz WHERE id = %s;", (contract_id,)
        )
        in_main = db.cursor.fetchone()[0]
        db.cursor.execute(
            "SELECT COUNT(*) FROM reestr_contract_44_fz_commission_work WHERE id = %s;",
            (contract_id,),
        )
        in_comm = db.cursor.fetchone()[0]
        print(f"  main: {in_main}, commission_work: {in_comm}")

        # 2) Условие "неясный": end_date < CURRENT_DATE - 60 days
        print("→ Двигаем end_date в прошлом, чтобы контракт попал в 'неясный'")
        db.cursor.execute(
            """
            UPDATE reestr_contract_44_fz_commission_work
            SET end_date = CURRENT_DATE - INTERVAL '61 days',
                delivery_start_date = NULL
            WHERE id = %s;
            """,
            (contract_id,),
        )
        db.connection.commit()

        c44 = migrate_from_commission_work("44")
        print(f"  migrate_from_commission_work('44') после 'неясный' вернул: {c44}")

        db.cursor.execute(
            "SELECT COUNT(*) FROM reestr_contract_44_fz_commission_work WHERE id = %s;",
            (contract_id,),
        )
        in_comm2 = db.cursor.fetchone()[0]
        db.cursor.execute(
            "SELECT COUNT(*) FROM reestr_contract_44_fz_unclear WHERE id = %s;",
            (contract_id,),
        )
        in_unclear = db.cursor.fetchone()[0]
        print(f"  commission_work: {in_comm2}, unclear: {in_unclear}")

        # 3) Условие "Разыгранные" — создадим ещё один тестовый контракт
        contract_number2 = f"{contract_number}-AWARDED"
        print(f"\n→ Создаём второй тестовый контракт для статуса 'Разыгранные': {contract_number2}")
        db.cursor.execute(
            """
            INSERT INTO reestr_contract_44_fz
                (contract_number, tender_link, auction_name,
                 start_date, end_date,
                 initial_price, customer_id, contractor_id,
                 region_id, okpd_id, trading_platform_id)
            VALUES
                (%s, %s, %s,
                 %s, %s,
                 %s, NULL, NULL,
                 NULL, NULL, NULL)
            RETURNING id;
            """,
            (
                contract_number2,
                "https://test.example/contract2",
                "Тестовая закупка (разыгранные)",
                now.date(),
                (now + timedelta(days=1)).date(),
                2000.0,
            ),
        )
        contract_id2 = db.cursor.fetchone()[0]
        db.connection.commit()
        print(f"  ✅ Вставлен контракт id={contract_id2}")

        print("→ Миграция во 'Работа комиссии' для второго контракта")
        migrate_from_main_to_commission_work("44")

        print("→ Ставим delivery_start_date, чтобы контракт попал в 'Разыгранные'")
        db.cursor.execute(
            """
            UPDATE reestr_contract_44_fz_commission_work
            SET delivery_start_date = CURRENT_DATE
            WHERE id = %s;
            """,
            (contract_id2,),
        )
        db.connection.commit()

        c44_2 = migrate_from_commission_work("44")
        print(f"  migrate_from_commission_work('44') после 'Разыгранные' вернул: {c44_2}")

        db.cursor.execute(
            "SELECT COUNT(*) FROM reestr_contract_44_fz_commission_work WHERE id = %s;",
            (contract_id2,),
        )
        in_comm3 = db.cursor.fetchone()[0]
        db.cursor.execute(
            "SELECT COUNT(*) FROM reestr_contract_44_fz_awarded WHERE id = %s;",
            (contract_id2,),
        )
        in_awarded = db.cursor.fetchone()[0]
        print(f"  commission_work: {in_comm3}, awarded: {in_awarded}")

        print("\n✅ Ускоренный прогон тестовых контрактов по всем статусам завершён")

        return contract_number, contract_number2

    finally:
        db.close()


def cleanup_test_contracts(patterns):
    print_header("Шаг 4: Очистка тестовых данных")
    db = DatabaseManager()
    try:
        for pattern in patterns:
            print(f"→ Удаляем контракты с contract_number LIKE '{pattern}%' из всех статусных таблиц")
            for table in [
                "reestr_contract_44_fz",
                "reestr_contract_44_fz_commission_work",
                "reestr_contract_44_fz_unclear",
                "reestr_contract_44_fz_awarded",
            ]:
                db.cursor.execute(
                    f"DELETE FROM {table} WHERE contract_number LIKE %s;",
                    (pattern + "%",),
                )
            db.connection.commit()
        print("✅ Тестовые данные удалены")
    finally:
        db.close()


def main():
    print_header("ТЕСТ МОДУЛЯ daily_status_migration")

    # 1. Принудительный бэкап
    force_backup_test()

    # 2. Миграции и сводка по количеству записей
    migration_counts_test()

    # 3. Ускоренный прогон одной тестовой закупки по всем статусам
    base_cn, awarded_cn = fast_path_single_contract()

    # 4. Очистка тестовых данных
    cleanup_test_contracts([base_cn, awarded_cn])

    print_header("ТЕСТ ЗАВЕРШЁН")


if __name__ == "__main__":
    # Скрипт запускается отдельно от основной программы:
    #   source venv/bin/activate
    #   python3 tests/test_status_migration.py
    main()

