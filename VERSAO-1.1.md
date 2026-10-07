# PIRAXIS 1.1 — correção da interface e pacote separado

O código original já usa as abas Painel, Série temporal, Conferência e Dados,
e os rótulos De e Até para o intervalo de datas. As palavras estranhas relatadas
são compatíveis com tradução automática do navegador. A versão 1.1 declara
pt-BR e impede a tradução do documento; datas, fontes e cálculos permanecem iguais.

## Preservação

- Branch original: claude/confident-turing-1NV8t.
- Commit original: 84f3e67af93d6e5726a7f6e439eabee06a0dbb63.
- Backup recuperável: backup/v1-original-2026-10-07-84f3e67, criado e conferido antes das edições.
- Branch separada: piraxis-1.1-interface.
- Release anterior: pacote-windows, preservada.
- ZIP anterior: PIRAXIS-windows-x64.zip.
- SHA256 anterior: 23cdc7940b736821c7b6aea3b2b5c65d6d2f16539c4a02f0b67b1bbbb4ddfacc.

## Windows

O workflow desta branch verifica pytest, o fluxo simulado e os rótulos/atributos
de idioma no Chromium antes de empacotar com o lock existente. Cria exclusivamente
a release v1.1 e o arquivo PIRAXIS-1.1-windows-x64.zip; falha se a release já existir.
Não move a tag antiga, não sobrescreve assets e não faz merge ou deploy.

Quando o build concluir, baixe o ZIP da release v1.1 e extraia em C:\PIRAXIS-1.1.
Mantenha a pasta anterior. Abra INICIAR PIRAXIS.bat. A versão no rodapé inclui
1.1, commit e data; use VERIFICAR INSTALACAO.bat para o autoteste offline.
Confira o ZIP com certutil -hashfile PIRAXIS-1.1-windows-x64.zip SHA256,
comparando com SHA256SUMS-1.1.txt.

Os screenshots originais foram resolvidos na Library, mas os pixels não puderam
ser materializados/inspecionados neste executor: o terminal falhou antes de iniciar.
O diagnóstico de tradução é uma inferência do relato e dos rótulos reais no código.
A imagem interface-1.1.png da nova release é produzida pela verificação no Chromium.
