library(tidyverse)

# Get Qualtrics Survey -------------
# Sys.getenv('QUALTRICS_BASE_URL')
# Sys.setenv('QUALTRICS_BASE_URL' = "vuamsterdam.eu.qualtrics.com")
# Sys.setenv('QUALTRICS_API_KEY' = readline("Please set your Qualtrics API key in the QUALTRICS_API_KEY environment variable: ")) 
# RESTART R
# readRenviron("~/.Renviron")
names(Sys.getenv()) %[in~% "QUAL"



# Assumption that all surveys have identical question ids!
update_participants <- function(csv_path, survey){
  surveys <- qualtRics::all_surveys()
  
  new_participants <-
    surveys[grepl(surveys$name, survey)]$id %>% 
    map_dfr(~{
      qualtRics::fetch_survey(
        surveyID = .x,
        verbose = T,
        breakout_sets = F
      ) %>% select(email, did = bs_did, prolific_id = PROLIFIC_ID, lang = surveylang) %>% 
        distinct()
    })
  
  # Get already existing participants database    
  participants <- read_csv(csv_path)
  start <- nrow(participants)
  
  # Read current mail-updater csv
  participants <- new_participants %>% 
    full_join(participants, .)
  
  participants <- 
    participants %>% 
    mutate(
      email = ifelse(
        is.na(email) & !is.na(prolific_id), 
        paste0(prolific_id, "@email.prolific.com"), 
        email
      )
    )
  message(paste0(nrow(participants)-start, " new participant rows found."))  
  
  # Drop incompletes
  participants <- 
    participants %>% 
    filter(!is.na(email) & !is.na(did))
  
  message(paste0(nrow(participants)-start, " new complete rows added."))  
  # Export updated csv
  write_csv(participants, csv_path)
}


survey = "NEWSFLOWS_pretreat_v1.0"
csv_path = '/Users/p.m.mendozauva.nl/Work/VUPD/projects/NEWSFLOWS/mail-updater/data/participants.csv'
update_participants(csv_path, survey)
