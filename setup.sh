#!/bin/bash

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🚀 Начинаю настройку окружения для MutationBenchmark...${NC}"

# 1. Проверка наличия python3
if ! command -v python3 &> /dev/null
then
    echo "❌ Ошибка: python3 не найден. Установите Python перед запуском."
    exit 1
fi

# 2. Создание виртуального окружения, если его еще нет
if [ ! -d "venv" ]; then
    echo -e "${BLUE}📦 Создаю виртуальное окружение (venv)...${NC}"
    python3 -m venv venv
    echo -e "${GREEN}✅ Окружение создано.${NC}"
else
    echo -e "${BLUE}ℹ️ Виртуальное окружение уже существует.${NC}"
fi

# 3. Установка библиотек
echo -e "${BLUE}⏳ Обновляю pip и устанавливаю библиотеки...${NC}"
./venv/bin/python3 -m pip install --upgrade pip
./venv/bin/python3 -m pip install -r requirements.txt

# 4. Создание директорий
mkdir -p src/main/java src/test/java

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Все библиотеки успешно установлены!${NC}"
else
    echo "❌ Произошла ошибка при установке библиотек."
    exit 1
fi

echo -e "\n${GREEN}✨ Настройка завершена.${NC}"
echo -e "Теперь можно запустить бенчмарк одной командой:"
echo -e "${BLUE}./venv/bin/python3 run_benchmark.py --path <путь_к_модулям> --iterations <кол-во итераций>${NC}"
echo -e "\nИли сначала войти в окружение вручную: ${BLUE}source venv/bin/activate${NC}"