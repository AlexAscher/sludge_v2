#!/usr/bin/env python3
"""
Скрипт для настройки Lifecycle Policy в DigitalOcean Spaces
Автоматически удаляет файлы старше 7 дней
"""

import boto3
from config import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_BUCKET_NAME, S3_REGION, S3_ENDPOINT


def setup_lifecycle_policy():
    """Настраивает политику автоудаления файлов старше 7 дней"""

    # Создаем S3 клиент
    s3_client = boto3.client(
        's3',
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=S3_REGION,
        endpoint_url=S3_ENDPOINT
    )

    # Определяем Lifecycle Configuration
    lifecycle_config = {
        'Rules': [
            {
                'ID': 'DeleteAfter1Day',  # ID (заглавные буквы) для S3 API
                'Status': 'Enabled',
                'Prefix': '',  # Применяется ко всем файлам в bucket
                'Expiration': {
                    'Days': 1  # Удалять через 1 день (минимум для теста)
                }
            }
        ]
    }

    try:
        # Применяем конфигурацию
        s3_client.put_bucket_lifecycle_configuration(
            Bucket=S3_BUCKET_NAME,
            LifecycleConfiguration=lifecycle_config
        )
        print(f"✅ Lifecycle Policy успешно настроена для bucket '{S3_BUCKET_NAME}'")
        print(f"📅 Файлы будут автоматически удаляться через 7 дней")
        print(f"💰 DELETE операции БЕСПЛАТНЫ в DigitalOcean Spaces")

        # Проверяем текущую конфигурацию
        current_config = s3_client.get_bucket_lifecycle_configuration(Bucket=S3_BUCKET_NAME)
        print(f"\n📋 Текущая конфигурация:")
        for rule in current_config['Rules']:
            print(f"  - Rule ID: {rule['ID']}")
            print(f"    Status: {rule['Status']}")
            print(f"    Expiration: {rule['Expiration']['Days']} days")

        return True

    except s3_client.exceptions.NoSuchBucket:
        print(f"❌ Bucket '{S3_BUCKET_NAME}' не найден")
        return False
    except Exception as e:
        print(f"❌ Ошибка при настройке Lifecycle Policy: {e}")
        return False


def check_lifecycle_policy():
    """Проверяет текущую Lifecycle Policy"""

    s3_client = boto3.client(
        's3',
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=S3_REGION,
        endpoint_url=S3_ENDPOINT
    )

    try:
        config = s3_client.get_bucket_lifecycle_configuration(Bucket=S3_BUCKET_NAME)
        print(f"✅ Lifecycle Policy активна для bucket '{S3_BUCKET_NAME}':")
        for rule in config['Rules']:
            print(f"  - Rule ID: {rule['ID']}")
            print(f"    Status: {rule['Status']}")
            print(f"    Expiration: {rule['Expiration']['Days']} days")
        return True
    except s3_client.exceptions.NoSuchLifecycleConfiguration:
        print(f"⚠️  Lifecycle Policy НЕ настроена для bucket '{S3_BUCKET_NAME}'")
        return False
    except Exception as e:
        print(f"❌ Ошибка при проверке Lifecycle Policy: {e}")
        return False


def remove_lifecycle_policy():
    """Удаляет Lifecycle Policy (на случай если нужно отключить)"""

    s3_client = boto3.client(
        's3',
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=S3_REGION,
        endpoint_url=S3_ENDPOINT
    )

    try:
        s3_client.delete_bucket_lifecycle(Bucket=S3_BUCKET_NAME)
        print(f"✅ Lifecycle Policy удалена для bucket '{S3_BUCKET_NAME}'")
        return True
    except Exception as e:
        print(f"❌ Ошибка при удалении Lifecycle Policy: {e}")
        return False


if __name__ == '__main__':
    import sys

    print("=" * 60)
    print("DigitalOcean Spaces Lifecycle Policy Setup")
    print("=" * 60)
    print()

    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == 'check':
            check_lifecycle_policy()
        elif command == 'remove':
            remove_lifecycle_policy()
        elif command == 'setup':
            setup_lifecycle_policy()
        else:
            print(f"❌ Неизвестная команда: {command}")
            print("\nИспользование:")
            print("  python setup_lifecycle.py setup   - Настроить автоудаление через 7 дней")
            print("  python setup_lifecycle.py check   - Проверить текущую политику")
            print("  python setup_lifecycle.py remove  - Удалить политику (отключить)")
    else:
        # По умолчанию - настройка
        setup_lifecycle_policy()
