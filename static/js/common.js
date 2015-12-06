$(function() {
    $('.start-hidden').hide().removeClass('start-hidden');
    
    $('body').on('DOMNodeInserted', '.start-hidden', function () {
        $(this).hide().removeClass('start-hidden');
    });
})