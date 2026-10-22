#!/usr/bin/env escript
%%! -noshell
%% Persistent squeal REPL: читает список абстрактных форм (как Erlang-терм),
%% вычисляет erl_eval:exprs с живыми bindings и отвечает строкой `OK Value` / `ERR Reason`.

main(_) ->
    loop(erl_eval:new_bindings()).

loop(Bindings) ->
    case io:get_line("") of
        eof ->
            halt(0);
        Line ->
            Chars = string:trim(Line),
            case parse_forms(Chars) of
                {ok, Forms} ->
                    try erl_eval:exprs(Forms, Bindings) of
                        {value, Value, NewBindings} ->
                            io:put_chars("OK " ++ io_lib:format("~p", [Value]) ++ "\n"),
                            loop(NewBindings);
                        Other ->
                            io:put_chars("ERR " ++ io_lib:format("~p", [Other]) ++ "\n"),
                            loop(Bindings)
                    catch
                        Class:Reason ->
                            io:put_chars("ERR " ++ io_lib:format("~p", [{Class, Reason}]) ++ "\n"),
                            loop(Bindings)
                    end;
                {error, Reason} ->
                    io:put_chars("ERR " ++ io_lib:format("~p", [Reason]) ++ "\n"),
                    loop(Bindings)
            end
    end.

parse_forms(Chars) ->
    case erl_scan:string(Chars) of
        {ok, Tokens, _} ->
            case erl_parse:parse_term(Tokens) of
                {ok, Forms} when is_list(Forms) -> {ok, Forms};
                {ok, Other} -> {ok, [Other]};
                {error, E} -> {error, E}
            end;
        {error, E, _} -> {error, E}
    end.
