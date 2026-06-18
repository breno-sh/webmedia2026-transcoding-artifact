# Portfolio de Experimentos - Fase 3 (Melhoria 1)

Este diretório contém todos os artefatos, scripts e resultados produzidos durante a execução da **Melhoria 1** da Fase 3 do artigo.

## Estrutura de Arquivos

### Scripts Principais
- **`run_all_experiments.py`**: O orquestrador mestre. Gerencia o orçamento de 32 vCPUs e executa múltiplas configurações em paralelo. Foi atualizado para ignorar a família T (throttled).
- **`phase3_unified.py`**: O script de execução que roda dentro de cada worker/instância. Realiza 30 repetições internamente para otimizar o uso da instância.

### Utilitários
- **`check_throttling.py`**: Script utilizado para verificar os créditos de CPU no CloudWatch, confirmando o travamento das instâncias T3.micro.

### Documentação e Resultados
- **`walkthrough.md`**: Resumo detalhado dos resultados técnicos, tempos médios e principais descobertas da Melhoria 1.
- **`task.md`**: Checklist de progresso de todas as tarefas da Fase 3.
- **`README.md`**: Este arquivo de índice.

### Logs
- O subdiretório `logs/` contém todos os arquivos `.log` individuais de cada configuração, incluindo os resultados agregados de 30 execuções.

## Vídeos Utilizados
- **Input**: `./artifacts/test_videos/video_repetido_10min.mp4`
- **Características**: 10 minutos de duração (600 segundos).
- **Justificativa**: Conforme o artigo (Seção 3.2), este vídeo é longo o suficiente para justificar a segmentação na estratégia Horizontal.

## Resumo de Resultados (Melhoria 1)
As famílias **M5** e **C5** foram testadas com sucesso para os codecs **H.265** e **VP9**.

| Métrica | Serial | Horizontal | Vertical |
| :--- | :--- | :--- | :--- |
| **Tempo Médio (VP9)** | ~415s | **~60s** | ~340s - 390s |
| **Tempo Médio (H.265)** | ~300s | **~58s** | ~250s - 300s |

> **Conclusão**: A escalabilidade Horizontal apresentou um ganho de performance de até 7x em relação à Serial e Vertical para o vídeo de 10 minutos.

---
*Gerado automaticamente em 15/03/2026*
