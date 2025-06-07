# This is my custom Fish config, managed locally!
if status is-interactive
    # Commands to run in interactive sessions can go here
end

function mkcd
    mkdir -p $argv
    and cd $argv
end


# --- Aliases ---
alias .. "cd ../"
alias ... "cd ../../"
alias .... "cd ../../../"
alias ..... "cd ../../../../"
alias ll "ls -alh"
alias l "clear"
alias d "docker"
alias dc "docker compose"
alias dps "docker ps -a"
alias di "docker images"
alias dv "docker volume ls"
alias dn "docker network ls"
alias dexec "docker exec -it"
alias dlogs "docker logs -f"
alias drmc "docker ps -aq | xargs docker rm"
alias drmv "docker volume ls -q | xargs docker volume rm"
alias ld "lazydocker"
alias zj "zellij"
alias g "git"
alias gs "git status"
alias ga "git add"
alias gaa "git add -A ."
alias gc "git commit -m"
alias gca "git commit -a -m"
alias gp "git push"
alias gpl "git pull"
alias gb "git branch"
alias gco "git checkout"
alias glog "git log --graph --oneline --decorate --all"
alias gdiff "git diff"
alias gstash "git stash"
alias gstashp "git stash pop"
alias c "code ."


# --- Color Theme ---
set -g fish_color_autosuggestion '555'  'brblack'
set -g fish_color_cancel -r
set -g fish_color_command --bold
set -g fish_color_comment red
set -g fish_color_cwd green
set -g fish_color_cwd_root red
set -g fish_color_end brmagenta
set -g fish_color_error brred
set -g fish_color_escape 'bryellow'  '--bold'
set -g fish_color_history_current --bold
set -g fish_color_host normal
set -g fish_color_match --background=brblue
set -g fish_color_normal normal
set -g fish_color_operator bryellow
set -g fish_color_param cyan
set -g fish_color_quote yellow
set -g fish_color_redirection brblue
set -g fish_color_search_match 'bryellow'  '--background=brblack'
set -g fish_color_selection 'white'  '--bold'  '--background=brblack'
set -g fish_color_user brgreen
set -g fish_color_valid_path --underline


# --- Environment Variables & Path ---
set -gx PATH "$HOME/.local/bin" $PATH

# --- ASDF setup for Fish shell ---
# This check is important! It ensures sourcing doesn't fail if the file isn't there yet.
if test -f "$HOME/.asdf/asdf.fish"
  source "$HOME/.asdf/asdf.fish"
end

set -U fish_greeting
set -gx UV_LINK_MODE copy

# Welcome message
echo "Welcome to your Coder workspace, powered by Fish!"
