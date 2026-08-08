# Analiza wniosków do projektu Planu Ogólnego Wrocławia

W kwietniu oraz maju 2026 we Wrocławiu przeprowadzane były konsultacje społeczne do projektu Planu Ogólnego miasta Wrocławia.
Plan Ogólny to nowy akt prawa miejscowego, zastępujący dotychczasowe Studium uwarunkowań i kierunków zagospodarowania przestrzennego. 

Etap składania wniosków został zakończony 15 maja 2026 r., a oficjalne podsumowanie konsultacji wraz z wykazem przetworzonych wniosków Urząd Miejski Wrocławia opublikował 7 sierpnia 2026 r.

## Cel projektu

**To repozytorium zawiera niezależną analizę danych wyekstrahowanych z oficjalnego wykazu wniosków oraz innych danych uzyskanych od Urzędu Miasta.**

Głównym celem jest uzyskanie rzetelnych, powtarzalnych i w pełni audytowalnych danych statystycznych dotyczących:
* skali i przebiegu procesu konsultacji,
* liczby wniosków złożonych w poszczególnych sprawach (m.in. transport zbiorowy, ochrona terenów zielonych),
* struktury przestrzennej i tematycznej aktywności mieszkańców.

> **Uwaga:** To repozytorium **nie analizuje** ostatecznych zapisów samego projektu Planu Ogólnego ani ustaleń urbanistycznych. Skupia się wyłącznie na ilościowej i jakościowej analizie etapu konsultacji społecznych (wniosków mieszkańców).


## Materiały źródłowe

Wszystkie oryginalne pliki źródłowe (wraz z zachowanym oznaczeniem pochodzenia) znajdują się w katalogu `data/raw/`.

### Ograniczenia danych i ich rekonstrukcja

Zarówno wykaz uwag jak i dane prezentowane na serwerach GIS agregują poszczególne uwagi w obrębie jednego wniosku. Nawet jeśli jeden wniosek dotyczył wielu działek albo nawet obszarów na przeciwległych krańcach miasta, to jest prezentowany jako jeden wiersz w podsumowaniu i jeden punkt na mapie.

W związku z tym w trakcie przetwarzania danych tworzona jest forma pośrednia która odtwarza przybliżone właściwe lokalizacje składanych uwag.

Urząd udostępnia też źródłowe wnioski w postaci skanów. Zostały one wykorzystane do wybiórczego zwalidowania zrekonstruowanych danych.

## Narzędzia SI

W procesie analizy wykorzystano wsparcie modeli językowych Gemini (Google), GPT-5.6-luna (OpenAI) przy bezpośrednim nadzorze człowieka (*augmentation and not agency*).

## Jak cytować

Jeśli wykorzystujesz wyniki tej analizy, dane przetworzone lub kod w swoich artykułach, publikacjach lub materiałach prasowych, proszę o powołanie się na to źródło:

> Biegaj, Ł. (2026). *Niezależna analiza wniosków mieszkańców do projektu Planu Ogólnego Wrocławia* [Zestawienie danych i kod źródłowy]. GitHub: `https://github.com/lpiob/wroclaw-plan-ogolny-analiza-konsultacji`

```bibtex
@misc{biegaj2026wroclaw,
  author = {Biegaj, Łukasz},
  title = {Niezależna analiza wniosków mieszkańców do projektu Planu Ogólnego Wrocławia},
  year = {2026},
  publisher = {GitHub},
  journal = {GitHub repository},
  howpublished = {\url{[https://github.com/lpiob/wroclaw-plan-ogolny-analiza-konsultacji](https://github.com/lpiob/wroclaw-plan-ogolny-analiza-konsultacji)}}
}

