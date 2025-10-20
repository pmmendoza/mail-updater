#!/usr/bin/env Rscript
suppressPackageStartupMessages(library(tidyverse))
suppressPackageStartupMessages(library(qualtRics))

parse_args <- function(args) {
  parsed <- list()
  i <- 1
  while (i <= length(args)) {
    key <- args[[i]]
    if (startsWith(key, "--")) {
      value <- if (i + 1 <= length(args)) args[[i + 1]] else NA_character_
      parsed[[substr(key, 3, nchar(key))]] <- value
      i <- i + 2
    } else {
      i <- i + 1
    }
  }
  parsed
}

args <- parse_args(commandArgs(trailingOnly = TRUE))
csv_path <- args[["csv-path"]]
if (is.null(csv_path) || is.na(csv_path) || csv_path == "") {
  stop("Missing --csv-path argument.")
}

survey_filter <- args[["survey-filter"]]
if (is.null(survey_filter) || is.na(survey_filter) || survey_filter == "") {
  survey_filter <- Sys.getenv("QUALTRICS_SURVEY_FILTER", unset = "")
}
if (survey_filter == "") {
  survey_filter <- NULL
}

qual_base <- Sys.getenv("QUALTRICS_BASE_URL", unset = "")
qual_token <- Sys.getenv("QUALTRICS_API_KEY", unset = "")

if (qual_base == "" || qual_token == "") {
  stop("QUALTRICS_BASE_URL and QUALTRICS_API_KEY must be set before running this script.")
}

qualtRics::qualtrics_api_credentials(api_key = qual_token, base_url = qual_base)

read_existing <- function(path) {
  if (!file.exists(path)) {
    return(tibble(email = character(), did = character(), status = character(), type = character()))
  }
  readr::read_csv(path, show_col_types = FALSE, progress = FALSE) %>%
    dplyr::mutate(
      email = stringr::str_trim(email),
      did = stringr::str_trim(did),
      status = dplyr::coalesce(status, "active"),
      type = dplyr::coalesce(type, "admin")
    ) %>%
    dplyr::filter(!is.na(did) & did != "")
}

fetch_participants <- function(survey_ids) {
  purrr::map_dfr(
    survey_ids,
    function(id) {
      qualtRics::fetch_survey(
        surveyID = id,
        verbose = TRUE,
        breakout_sets = FALSE
      ) %>%
        dplyr::select(
          email = dplyr::any_of("email"),
          did = dplyr::any_of("bs_did"),
          prolific_id = dplyr::any_of("PROLIFIC_ID")
        ) %>%
        dplyr::mutate(
          email = dplyr::coalesce(
            email,
            dplyr::if_else(
              !is.na(prolific_id) & prolific_id != "",
              paste0(prolific_id, "@email.prolific.com"),
              NA_character_
            )
          ),
          did = stringr::str_trim(did),
          email = stringr::str_trim(email)
        ) %>%
        dplyr::filter(!is.na(email) & email != "" & !is.na(did) & did != "") %>%
        dplyr::mutate(
          status = "active",
          type = dplyr::if_else(
            !is.na(prolific_id) & prolific_id != "",
            "prolific",
            "pilot"
          )
        ) %>%
        dplyr::select(email, did, status, type) %>%
        dplyr::distinct(did, .keep_all = TRUE)
    }
  )
}

existing <- read_existing(csv_path)

surveys <- qualtRics::all_surveys() %>%
  dplyr::filter(!is.na(name))

if (!is.null(survey_filter)) {
  surveys <- dplyr::filter(surveys, stringr::str_detect(name, survey_filter))
}

if (nrow(surveys) == 0) {
  message("No surveys matched filter; keeping existing participants.")
  readr::write_csv(existing, csv_path, na = "")
  quit(status = 0)
}

new_participants <- fetch_participants(surveys$id)

if (nrow(new_participants) == 0) {
  message("No new participants found; keeping existing participants.")
  readr::write_csv(existing, csv_path, na = "")
  quit(status = 0)
}

combined <- existing %>%
  dplyr::full_join(new_participants, by = "did", suffix = c("_existing", "_new")) %>%
  dplyr::mutate(
    email = dplyr::coalesce(email_existing, email_new),
    status = dplyr::coalesce(status_existing, status_new, "active"),
    type = dplyr::coalesce(type_existing, type_new, "prolific")
  ) %>%
  dplyr::select(email, did, status, type) %>%
  dplyr::distinct(did, .keep_all = TRUE) %>%
  dplyr::arrange(email)

added <- dplyr::anti_join(combined, existing, by = "did")
message(paste0(nrow(added), " new participant rows merged."))

readr::write_csv(combined, csv_path, na = "")
