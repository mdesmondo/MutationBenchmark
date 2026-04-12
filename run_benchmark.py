import os
import re
import time
import shutil
import subprocess
import psutil
import platform
import csv
import argparse
import statistics
from datetime import datetime
from pathlib import Path
# --- ИМПОРТЫ ДЛЯ АНАЛИТИКИ ---
try:
    import pandas as pd
    import matplotlib.pyplot as plt
    import seaborn as sns
    from scipy import stats
except ImportError:
    print("❌ Ошибка: Не установлены библиотеки для аналитики.")
    print("Выполни в терминале: chmod +x setup.sh && ./setup.sh")
    exit(1)

# --- КОНФИГУРАЦИЯ ---
TEMPLATE_SRC_DIR = Path("src")
DOCS_DIR = Path("docs")
MVN_CMD = "mvn.cmd" if platform.system() == "Windows" else "mvn"

def count_loc(raw_module_path):
    """Считает общее количество непустых строк во всех .java файлах"""
    total_lines = 0
    java_files = list(raw_module_path.rglob("*.java"))
    for file in java_files:
        try:
            with open(file, 'r', encoding='utf-8') as f:
                # считаем только те строки, где есть хоть какие-то символы кроме пробелов
                total_lines += sum(1 for line in f if line.strip())
        except Exception:
            pass
    return total_lines

def extract_package_name(file_path):
    package_pattern = re.compile(r'^\s*package\s+([a-zA-Z0-9_.]+)\s*;', re.MULTILINE)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            match = package_pattern.search(f.read())
            if match: return match.group(1)
    except Exception: pass
    return ""

# Добавили второй аргумент helper_path (по умолчанию None)
def inject_module_to_src(raw_module_path, helper_path=None):
    """Очищает код, подтягивает общие файлы и записывает всё в src"""
    if TEMPLATE_SRC_DIR.exists(): shutil.rmtree(TEMPLATE_SRC_DIR)
    if DOCS_DIR.exists(): shutil.rmtree(DOCS_DIR)

    java_files = list(raw_module_path.rglob("*.java"))
    if not java_files: return False

    # Вся логика должна быть ВНУТРИ проверки на наличие helper_path
    if helper_path:
        common_dir = Path(helper_path)
        if common_dir.exists():
            java_files.extend(list(common_dir.rglob("*.java")))
        else:
            print(f"  ⚠️ Внимание: Папка с хелперами {helper_path} не найдена.")

    package_name = "org.example"
    package_path = "org/example"

    for java_file in java_files:
        is_test = "test" in java_file.name.lower() or "helper" in java_file.name.lower()

        try:
            with open(java_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            cleaned_lines = [f"package {package_name};\n\n"]
            if is_test:
                cleaned_lines.append("import org.junit.Test;\n")
                cleaned_lines.append("import static org.junit.Assert.*;\n\n")

            forbidden_prefixes = (
                "package ", "import java_programs", "import correct_java_programs",
                "import java_testcases", "import Node", "import WeightedNode"
            )
            garbage_strings = [
                "java_programs.", "correct_java_programs.",
                "java_testcases.junit.", "java_testcases."
            ]

            for line in lines:
                if any(line.strip().startswith(p) for p in forbidden_prefixes):
                    continue

                for g in garbage_strings:
                    line = line.replace(g, "")

                line = re.sub(r'\b((?:public|private|protected)\s+)?class\s+',
                              lambda m: m.group(0) if m.group(1) else 'public class ',
                              line)

                if is_test:
                    line = re.sub(r'\b((?:public|private|protected)\s+)?void\s+test',
                                  lambda m: m.group(0) if m.group(1) else 'public void test',
                                  line)

                cleaned_lines.append(line)

            target_sub = "test/java" if is_test else "main/java"
            target_dir = TEMPLATE_SRC_DIR / target_sub / package_path
            target_dir.mkdir(parents=True, exist_ok=True)

            with open(target_dir / java_file.name, 'w', encoding='utf-8') as f:
                f.writelines(cleaned_lines)

        except Exception as e:
            print(f"  ⚠️ Ошибка обработки {java_file.name}: {e}")
            continue

    return True

def kill_process_tree(pid):
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            child.kill()
        parent.kill()
    except psutil.NoSuchProcess:
        pass

def measure_process(cmd_list, log_path, timeout=600):
    start_time = time.perf_counter()
    peak_ram = 0

    with open(log_path, 'w', encoding='utf-8') as log_file:
        try:
            process = subprocess.Popen(cmd_list, stdout=log_file, stderr=subprocess.STDOUT)
            ps_proc = psutil.Process(process.pid)

            while process.poll() is None:
                try:
                    total_ram = ps_proc.memory_info().rss
                    for c in ps_proc.children(recursive=True):
                        try:
                            total_ram += c.memory_info().rss
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    peak_ram = max(peak_ram, total_ram)
                    time.sleep(0.1)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    break

            process.wait(timeout=timeout)
            status = "success" if process.returncode == 0 else "error"

        except subprocess.TimeoutExpired:
            kill_process_tree(process.pid)
            status = "timeout"
        except Exception:
            if 'process' in locals():
                kill_process_tree(process.pid)
            status = "crash"

    return {"status": status, "time_sec": time.perf_counter() - start_time, "ram_mb": peak_ram / (1024 * 1024)}

def get_mutation_stats(module_dir):
    """Получение данных по работе фреймворков"""
    pit_csv = module_dir / "pit_mutations.csv"
    pit_html = module_dir / "pit-reports" / "index.html"
    p_gen = p_kill = p_score = 0
    p_line_cov = "N/A"
    pit_survivors = []

    if pit_html.exists():
        try:
            with open(pit_html, 'r', encoding='utf-8') as f:
                content = f.read()
                line_cov_match = re.search(r'<td>Line Coverage</td>\s*<td>\s*<div class="coverage_percentage">(\d+%)', content, re.IGNORECASE | re.DOTALL)
                if line_cov_match:
                    p_line_cov = line_cov_match.group(1)
                else:
                    any_pct = re.findall(r'<div class="coverage_percentage">(\d+%)', content)
                    if any_pct:
                        p_line_cov = any_pct[0]
        except Exception: pass

    if pit_csv.exists():
        with open(pit_csv, 'r', encoding='utf-8') as f:
            for r in csv.reader(f):
                if not r: continue
                if len(r) >= 6:
                    p_gen += 1
                    status = r[5].strip()
                    if status == 'KILLED':
                        p_kill += 1
                    elif status in ['SURVIVED', 'NO_COVERAGE']:
                        file_name = r[1]
                        method = r[3]
                        line_num = r[4]
                        mutator = r[2].split('.')[-1]
                        pit_survivors.append(f"Файл: `{file_name}`, Строка: **{line_num}** (метод `{method}`) | Мутатор: `{mutator}` | Статус: {status}")
            p_score = (p_kill / p_gen * 100) if p_gen > 0 else 0

    maj_log = module_dir / "major_mutants.log"
    maj_details = module_dir / "major_details.csv"
    mutants_info = {}

    if maj_log.exists():
        with open(maj_log, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip(): continue
                parts = line.split(':')
                if len(parts) >= 7:
                    m_id = parts[0].strip()
                    full_method = parts[4].strip()
                    class_part = full_method.split('@')[0]
                    file_name = class_part.split('.')[-1] + ".java"
                    method_name = full_method.split('@')[-1]

                    mutants_info[m_id] = {
                        "file": file_name,
                        "operator": parts[1].strip(),
                        "method": method_name,
                        "line_no": parts[5].strip(),
                        "transform": ":".join(parts[6:]).strip(),
                        "status": "LIVE (NOT_COVERED)"
                    }

    m_gen = len(mutants_info)

    if maj_details.exists():
        with open(maj_details, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                if not row: continue
                m_id = row[0].strip()
                status = row[-1].strip().upper()
                if m_id in mutants_info:
                    mutants_info[m_id]["status"] = status

    m_kill = 0
    major_survivors = []
    for m_id, info in mutants_info.items():
        if info["status"] in ['FAIL', 'EXC', 'TIME', 'TIMEOUT', 'KILLED']:
            m_kill += 1
        else:
            major_survivors.append(
                f"ID: `{m_id}` | Файл: `{info['file']}`, Строка: **{info['line_no']}** (метод `{info['method']}`) | "
                f"Мутатор: `{info['operator']}` | Преобразование: `{info['transform']}` | Статус: {info['status']}"
            )

    m_score = (m_kill / m_gen * 100) if m_gen > 0 else 0

    return {"gen": p_gen, "kill": p_kill, "score": p_score, "surv": pit_survivors, "line_cov": p_line_cov}, \
        {"gen": m_gen, "kill": m_kill, "score": m_score, "surv": major_survivors, "line_cov": "-"}

def generate_plots_and_analyze(run_dir):
    print("\n📊 Запуск генерации графиков и аналитики...")
    try:
        raw_df = pd.read_csv(run_dir / 'raw_metrics.csv')
        nir_df = pd.read_csv(run_dir / 'nir_data.csv')

        raw_df.columns = raw_df.columns.str.strip()
        nir_df.columns = nir_df.columns.str.strip()

        sns.set_theme(style="whitegrid", context="paper", font_scale=1.2)

        # 1. Время выполнения
        plt.figure(figsize=(12, 6))
        sns.boxplot(data=raw_df, x='Module', y='Time_Sec', hue='Framework', palette='Set2')
        plt.xticks(rotation=45, ha='right')
        plt.title('Распределение времени выполнения: Major vs PITest')
        plt.ylabel('Время (секунды)')
        plt.xlabel('Модуль')
        plt.tight_layout()
        plt.savefig(run_dir / 'time_comparison.png', dpi=300)
        plt.close()

        # 2. ОЗУ
        plt.figure(figsize=(12, 6))
        sns.boxplot(data=raw_df, x='Module', y='RAM_MB', hue='Framework', palette='Set1')
        plt.xticks(rotation=45, ha='right')
        plt.title('Потребление памяти (ОЗУ): Major vs PITest')
        plt.ylabel('ОЗУ (MB)')
        plt.xlabel('Модуль')
        plt.tight_layout()
        plt.savefig(run_dir / 'ram_comparison.png', dpi=300)
        plt.close()

        # 3. Mutation Score
        plt.figure(figsize=(12, 6))
        sns.barplot(data=nir_df, x='Module', y='Score', hue='Framework', palette='viridis')
        plt.xticks(rotation=45, ha='right')
        plt.title('Mutation Score (Процент убитых мутантов): Major vs PITest')
        plt.ylabel('Score (%)')
        plt.xlabel('Модуль')
        plt.tight_layout()
        plt.savefig(run_dir / 'score_comparison.png', dpi=300)
        plt.close()

        # 4. Сгенерированные мутанты
        plt.figure(figsize=(12, 6))
        sns.barplot(data=nir_df, x='Module', y='Generated', hue='Framework', palette='magma')
        plt.xticks(rotation=45, ha='right')
        plt.title('Сгенерированные мутанты: Major vs PITest')
        plt.ylabel('Количество')
        plt.xlabel('Модуль')
        plt.tight_layout()
        plt.savefig(run_dir / 'generated_comparison.png', dpi=300)
        plt.close()

        print(f"  ✅ Графики (4 шт.) успешно сохранены в: {run_dir}")

        # 5. Статистический анализ
        stat_file_path = run_dir / "stat_analysis.txt"
        with open(stat_file_path, "w", encoding="utf-8") as f:
            f.write("--- Статистическая значимость (Mann-Whitney U Test) для времени ---\n\n")
            modules = raw_df['Module'].unique()
            for module in modules:
                major_time = raw_df[(raw_df['Module'] == module) & (raw_df['Framework'] == 'Major')]['Time_Sec']
                pitest_time = raw_df[(raw_df['Module'] == module) & (raw_df['Framework'] == 'PITest')]['Time_Sec']

                if len(major_time) > 0 and len(pitest_time) > 0:
                    stat, p_value = stats.mannwhitneyu(major_time, pitest_time, alternative='two-sided')
                    significance = "ЗНАЧИМО" if p_value < 0.05 else "НЕ ЗНАЧИМО"
                    f.write(f"Модуль: {module:25} | P-value: {p_value:.4f} | Результат: {significance}\n")

        print(f"  ✅ Статистический анализ выгружен в: {stat_file_path.name}")
    except Exception as e:
        print(f"  ❌ Ошибка при генерации аналитики: {e}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True, help="Путь к папке (с модулями ИЛИ с .java файлами)")
    parser.add_argument("--iterations", type=int, default=3, help="Кол-во итераций (среднее)")
    parser.add_argument("--helper", default=None, help="Опциональный путь к директории с файлами-помощниками")
    args = parser.parse_args()

    target_dir = Path(args.path)
    if not target_dir.exists() or not target_dir.is_dir():
        print(f"❌ Ошибка: Путь {target_dir} не существует.")
        return

    subdirs = [d for d in target_dir.iterdir() if d.is_dir()]
    java_files = list(target_dir.glob("*.java"))

    if subdirs and not java_files:
        modules = subdirs
        print(f"🚀 Режим BATCH: Найдено {len(modules)} модулей в очереди.")
    elif java_files and not subdirs:
        modules = [target_dir]
        print(f"🚀 Режим SINGLE: Запуск единичного модуля из {target_dir.name}.")
    else:
        print("❌ Ошибка: В папке смешаны файлы и папки.")
        return

    run_dir = Path(f"analytics/run_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}")
    run_dir.mkdir(parents=True, exist_ok=True)
    metrics_file = run_dir / "raw_metrics.csv"

    with open(metrics_file, 'w', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow(["Module", "Framework", "Iteration", "Status", "Time_Sec", "RAM_MB"])

    results_for_report = []

    for idx, mod_path in enumerate(modules, 1):
        mod_name = mod_path.name
        print(f"📦 [{idx}/{len(modules)}] Модуль: {mod_name}")

        # считаем строки перед инъекцией
        loc_count = count_loc(mod_path)
        print(f"  📊 Объём кода: {loc_count} непустых строк.")

        # передаем args.helper вторым аргументом
        if not inject_module_to_src(mod_path, args.helper):
            print("  ⚠️ .java файлы не найдены, пропуск.")
            continue

        mod_archive = run_dir / mod_name
        mod_archive.mkdir(exist_ok=True)

        fw_data = {"Major": {"times": [], "rams": []}, "PITest": {"times": [], "rams": []}}

        for i in range(1, args.iterations + 1):
            print(f"  🔄 Итерация {i}/{args.iterations}...")

            # --- MAJOR ---
            log_m = mod_archive / f"major_iter_{i}.log"
            m = measure_process([MVN_CMD, "clean", "verify"], log_m)
            if m['status'] == 'success':
                fw_data["Major"]["times"].append(m['time_sec'])
                fw_data["Major"]["rams"].append(m['ram_mb'])

            with open(metrics_file, 'a', newline='', encoding='utf-8') as f:
                csv.writer(f).writerow([mod_name, "Major", i, m['status'], f"{m['time_sec']:.2f}", f"{m['ram_mb']:.2f}"])

            if i == 1 and m['status'] == 'success':
                major_docs = DOCS_DIR / "major-results"
                if major_docs.exists():
                    for f_name in ["summary.csv", "details.csv", "mutants.log"]:
                        src_file = major_docs / f_name
                        if src_file.exists():
                            shutil.copy2(src_file, mod_archive / f"major_{f_name}")

            # --- PITEST ---
            log_p = mod_archive / f"pitest_iter_{i}.log"
            p = measure_process([MVN_CMD, "clean", "test", "-P", "pitest", "-Dthreads=4"], log_p)
            if p['status'] == 'success':
                fw_data["PITest"]["times"].append(p['time_sec'])
                fw_data["PITest"]["rams"].append(p['ram_mb'])

            with open(metrics_file, 'a', newline='', encoding='utf-8') as f:
                csv.writer(f).writerow([mod_name, "PITest", i, p['status'], f"{p['time_sec']:.2f}", f"{p['ram_mb']:.2f}"])

            if i == 1 and p['status'] == 'success':
                pit_docs = DOCS_DIR / "pit-reports"
                if pit_docs.exists():
                    shutil.copytree(pit_docs, mod_archive / "pit-reports", dirs_exist_ok=True)
                    csvs = list(pit_docs.rglob("mutations.csv"))
                    if csvs:
                        shutil.copy2(csvs[0], mod_archive / "pit_mutations.csv")

        p_stats, m_stats = get_mutation_stats(mod_archive)
        results_for_report.append({
            "name": mod_name,
            "loc": loc_count,
            "Major": {"stats": m_stats, "time": statistics.mean(fw_data["Major"]["times"]) if fw_data["Major"]["times"] else 0, "ram": statistics.mean(fw_data["Major"]["rams"]) if fw_data["Major"]["rams"] else 0},
            "PITest": {"stats": p_stats, "time": statistics.mean(fw_data["PITest"]["times"]) if fw_data["PITest"]["times"] else 0, "ram": statistics.mean(fw_data["PITest"]["rams"]) if fw_data["PITest"]["rams"] else 0}
        })

    # --- ОТЧЕТ ---
    report_path = run_dir / "FINAL_REPORT.md"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(f"# Отчет бенчмарка ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n\n")
        f.write("## Сводная таблица\n")

        header = f"| {'Модуль':<20} | {'LOC':<6} | {'Фреймворк':<9} | {'Line Cov':<9} | {'Сгенер.':<7} | {'Score %':<8} | {'Avg Time':<8} |\n"
        sep = "|-" + "-"*20 + "|-" + "-"*6 + "|-" + "-"*9 + "|-" + "-"*9 + "|-" + "-"*7 + "|-" + "-"*8 + "|-" + "-"*8 + "|\n"
        f.write(header + sep)

        for r in results_for_report:
            for fw in ["Major", "PITest"]:
                d = r[fw]
                l_cov = d['stats'].get('line_cov', '-')
                line = f"| {r['name'][:20]:<20} | {r['loc']:<6} | {fw:<9} | {l_cov:<9} | {d['stats']['gen']:<7} | {d['stats']['score']:>6.2f}% | {d['time']:>6.2f}s |\n"
                f.write(line)

        f.write("\n## Детализация по модулям\n\n")
        for r in results_for_report:
            f.write(f"### 📦 Модуль: {r['name']} (Строк кода: {r['loc']})\n")
            pit_html_path = f"./{r['name']}/pit-reports/index.html"
            f.write(f"**Детальный HTML Отчет (PITest):** [Открыть в браузере]({pit_html_path})\n\n")

            p_surv = r['PITest']['stats']['surv']
            f.write(f"#### PITest: Выжившие мутанты ({len(p_surv)} шт.)\n")
            if p_surv:
                f.write("<details>\n<summary>Показать список</summary>\n\n")
                for s in p_surv: f.write(f"- {s}\n")
                f.write("\n</details>\n\n")

            m_surv = r['Major']['stats']['surv']
            f.write(f"#### Major: Выжившие мутанты ({len(m_surv)} шт.)\n")
            if m_surv:
                f.write("<details>\n<summary>Показать список</summary>\n\n")
                for s in m_surv: f.write(f"- {s}\n")
                f.write("\n</details>\n\n")
            f.write("---\n")

    print(f"\n ✅ Готово! Результаты сохранены в: {run_dir}")

    # --- ГЕНЕРАЦИЯ nir_data.csv ---
    nir_data_path = run_dir / "nir_data.csv"
    with open(nir_data_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Module", "Framework", "Generated", "Score"])
        for r in results_for_report:
            # записываем Major
            writer.writerow([r['name'], "Major", r['Major']['stats']['gen'], r['Major']['stats']['score']])
            # записываем PITest
            writer.writerow([r['name'], "PITest", r['PITest']['stats']['gen'], r['PITest']['stats']['score']])

    print(f"  ✅ Файл {nir_data_path.name} успешно сгенерирован.")

    # --- ЗАПУСК АВТОМАТИЧЕСКОЙ АНАЛИТИКИ ---
    generate_plots_and_analyze(run_dir)

    print(f"\n ✅ Пайплайн завершен! Все результаты, графики и отчеты лежат в: {run_dir}")

if __name__ == "__main__": main()